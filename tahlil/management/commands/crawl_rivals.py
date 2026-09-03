"""Crawl rival shops using our own products as the reference."""

from __future__ import annotations

import concurrent.futures as futures
import hashlib
import io
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from PIL import Image

from tahlil.matching.fingerprint import fingerprint_bytes
from tahlil.matching.match import verdict_for
from tahlil.matching.html_shop import HTML_SHOPS, HTML_SHOPS_BY_HOST
from tahlil.matching.marketplaces import MARKETS
from tahlil.matching.rivals import (
    SHOPS,
    SHOPS_BY_HOST,
    Candidate,
    build_queries,
    collect_all_candidates,
    fetch_image,
)
from tahlil.crawler_job import emit, stop_requested
from tahlil.models import Product, RivalProduct

CACHE_DIRNAME = "rival-cache"
THUMB_PX = 420


def cache_root() -> Path:
    root = Path(settings.BASE_DIR) / "data" / CACHE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_thumb(host: str, image_url: str, data: bytes) -> str:
    """Save a small local copy so the app still renders when offline."""
    name = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:20] + ".jpg"
    rel = f"{host}/{name}"
    dest = cache_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        im.thumbnail((THUMB_PX, THUMB_PX), Image.Resampling.LANCZOS)
        im.save(dest, "JPEG", quality=82)
    except Exception:
        return ""
    return rel


def _work(
    reference, queries, shops, html_shops, markets, per_page: int, pause: float, loose: bool
):
    """Network + hashing only. No ORM here so SQLite stays single-writer."""
    results: list[tuple[Candidate, dict, bytes]] = []
    if stop_requested():
        return reference["id"], queries, results
    emit("search", our=reference.get("name") or str(reference.get("id")), wp_id=reference.get("id"))
    candidates = collect_all_candidates(
        queries,
        shops=shops,
        html_shops=html_shops,
        markets=markets,
        per_page=per_page,
        pause=pause,
        our_family=reference.get("family") or "other",
        max_candidates=60 if loose else 30,
    )
    for cand in candidates:
        if stop_requested():
            break
        try:
            blob = fetch_image(cand.image_url)
            fp = fingerprint_bytes(blob)
        except Exception:
            continue
        verdict = verdict_for(reference, fp, cand.title, cand.family, loose=loose)
        if verdict["status"] in ("match", "uncertain"):
            results.append((cand, verdict, blob))
    return reference["id"], queries, results


class Command(BaseCommand):
    help = "Search rival shops for listings that look like our products"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25, help="how many of our products")
        parser.add_argument("--family", default="", help="only this product family")
        parser.add_argument("--id", type=int, action="append", help="specific product wp_id")
        parser.add_argument("--shop", action="append", help="restrict to these hosts")
        parser.add_argument(
            "--no-html",
            action="store_true",
            help="skip shops that must be read as HTML pages",
        )
        parser.add_argument(
            "--no-market",
            action="store_true",
            help="skip the nationwide marketplaces",
        )
        parser.add_argument(
            "--loose",
            action="store_true",
            help="keep weaker lookalikes as «شبیه» (the bar for match is unchanged)",
        )
        parser.add_argument("--per-page", type=int, default=10)
        parser.add_argument("--workers", type=int, default=4)
        parser.add_argument("--pause", type=float, default=0.25)
        parser.add_argument(
            "--skip-done",
            action="store_true",
            help="skip our products that already have rivals stored",
        )

    def handle(self, *args, **opts):
        shops = SHOPS
        html_shops = () if opts["no_html"] else HTML_SHOPS
        markets = () if opts["no_market"] else tuple(MARKETS)
        if opts["shop"]:
            wanted = set(opts["shop"])
            shops = tuple(SHOPS_BY_HOST[h] for h in wanted if h in SHOPS_BY_HOST)
            html_shops = tuple(
                HTML_SHOPS_BY_HOST[h]
                for h in wanted
                if h in HTML_SHOPS_BY_HOST and not opts["no_html"]
            )
            markets = tuple(
                h for h in wanted if h in MARKETS and not opts["no_market"]
            )
            unknown = wanted - set(SHOPS_BY_HOST) - set(HTML_SHOPS_BY_HOST) - set(MARKETS)
            if unknown:
                self.stderr.write(f"هاست ناشناس: {', '.join(sorted(unknown))}")
            if not shops and not html_shops and not markets:
                self.stderr.write("هیچ فروشگاه معتبری انتخاب نشد.")
                return

        qs = Product.objects.filter(status="publish").exclude(images__dhash="").distinct()
        if opts["family"]:
            qs = qs.filter(family=opts["family"])
        if opts["id"]:
            qs = qs.filter(wp_id__in=opts["id"])
        if opts["skip_done"]:
            qs = qs.filter(rivals__isnull=True)
        qs = qs.prefetch_related("images").order_by("wp_id")
        if opts["limit"] and not opts["id"]:
            qs = qs[: opts["limit"]]

        products = list(qs)
        if not products:
            self.stdout.write("محصولی برای جستجو نماند.")
            return

        jobs = []
        for product in products:
            reference = product.as_match_dict()
            queries = build_queries(product.name, product.family)
            if not queries:
                continue
            jobs.append((reference, queries))

        hosts = (
            [s.host for s in shops]
            + [f"{s.host} (صفحه)" for s in html_shops]
            + [f"{h} (بازار)" for h in markets]
        )
        mode = "حساسیت کم" if opts["loose"] else "سخت‌گیرانه"
        self.stdout.write(
            f"جستجو برای {len(jobs)} محصول در {len(hosts)} منبع [{mode}]: "
            + ", ".join(hosts)
        )
        emit("start", hosts=", ".join(hosts), our=len(jobs), mode=mode)

        by_wp = {p.wp_id: p for p in products}
        total_match = total_uncertain = 0
        stopped = False

        pool = futures.ThreadPoolExecutor(max_workers=opts["workers"])
        try:
            pending = [
                pool.submit(
                    _work,
                    reference,
                    queries,
                    shops,
                    html_shops,
                    markets,
                    opts["per_page"],
                    opts["pause"],
                    opts["loose"],
                )
                for reference, queries in jobs
            ]
            for done in futures.as_completed(pending):
                if stop_requested():
                    stopped = True
                    self.stdout.write("توقف از پنل.")
                    break
                try:
                    wp_id, queries, results = done.result()
                except Exception as exc:
                    self.stderr.write(f"  خطا: {exc}")
                    continue
                product = by_wp.get(wp_id)
                if product is None:
                    continue

                saved_match = saved_uncertain = 0
                with transaction.atomic():
                    for cand, verdict, blob in results:
                        rel = store_thumb(cand.shop_host, cand.image_url, blob)
                        RivalProduct.objects.update_or_create(
                            product=product,
                            url=cand.url,
                            defaults={
                                "shop_host": cand.shop_host,
                                "shop_name": cand.shop_name,
                                "rival_ref": cand.rival_ref,
                                "title": cand.title[:600],
                                "price": cand.price,
                                "currency": cand.currency,
                                "stock": cand.stock,
                                "image_url": cand.image_url,
                                "image_path": rel,
                                "verdict": verdict["status"],
                                "visual_score": verdict["visual"],
                                "title_score": verdict["title"],
                                "reasons": " | ".join(verdict["reasons"]),
                                "query_used": " ; ".join(queries)[:200],
                            },
                        )
                        if verdict["status"] == "match":
                            saved_match += 1
                        else:
                            saved_uncertain += 1
                        emit(
                            "hit",
                            shop=cand.shop_name or cand.shop_host,
                            host=cand.shop_host,
                            title=cand.title[:90],
                            url=cand.url,
                            verdict=verdict["status"],
                            our=product.name[:50],
                            price=cand.price,
                        )

                total_match += saved_match
                total_uncertain += saved_uncertain
                if saved_match or saved_uncertain:
                    self.stdout.write(
                        f"  {product.wp_id} {product.name[:44]} → "
                        f"match {saved_match} / شبیه {saved_uncertain}"
                    )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if stopped or stop_requested():
            self.stdout.write("کراول قطع شد.")
            emit("done", match=total_match, uncertain=total_uncertain, stopped=True)
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"تمام. match={total_match} شبیه={total_uncertain} "
                f"روی {len(jobs)} محصول"
            )
        )
        emit("done", match=total_match, uncertain=total_uncertain, stopped=False)
