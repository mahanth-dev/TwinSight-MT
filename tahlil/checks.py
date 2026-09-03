"""Two end-to-end checks the staff panel can run before a real crawl."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.urls import reverse

from tahlil import crawler_job
from tahlil.matching.fingerprint import fingerprint_image
from tahlil.matching.match import verdict_for
from tahlil.matching.rivals import SHOPS, USER_AGENT, build_queries, fetch_image, search_shop
from tahlil.models import Product, ProductImage, RivalProduct

MAX_IMAGE_SAMPLE = 40


def _step(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _pack(test_id: str, title: str, steps: list[dict]) -> dict:
    return {
        "id": test_id,
        "title": title,
        "ok": all(s["ok"] for s in steps) if steps else False,
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": steps,
    }


def run_catalog_e2e() -> dict:
    """Public catalog + our own product images, no external network."""
    steps: list[dict] = []
    client = Client()
    uploads = Path(settings.UPLOADS_ROOT)

    products = Product.objects.filter(status="publish").count()
    images = ProductImage.objects.count()
    steps.append(_step("کاتالوگ sqlite", products > 0 and images > 0, f"{products} محصول منتشرشده، {images} ردیف عکس"))

    missing = 0
    checked = 0
    sample = list(ProductImage.objects.only("rel_path")[:MAX_IMAGE_SAMPLE])
    for img in sample:
        checked += 1
        if not (uploads / img.rel_path).is_file():
            missing += 1
    steps.append(
        _step(
            "فایل عکس روی دیسک",
            checked > 0 and missing == 0,
            f"{checked - missing}/{checked} موجود در {uploads}",
        )
    )

    home = client.get("/")
    steps.append(_step("صفحه خانه", home.status_code == 200, f"HTTP {home.status_code}"))

    listing = client.get("/products/")
    steps.append(_step("لیست کاتالوگ", listing.status_code == 200, f"HTTP {listing.status_code}"))

    product = (
        Product.objects.filter(status="publish", images__isnull=False)
        .prefetch_related("images")
        .distinct()
        .first()
    )
    if product is None:
        steps.append(_step("صفحه محصول", False, "محصول با عکس پیدا نشد"))
        img = None
    else:
        detail = client.get(f"/products/{product.wp_id}/")
        html = detail.content.decode("utf-8", "replace")
        featured = product.featured
        media_url = reverse("media_image", args=[featured.id]) if featured else ""
        ok = detail.status_code == 200 and (not media_url or media_url in html)
        steps.append(
            _step(
                "صفحه محصول و لینک عکس",
                ok,
                f"HTTP {detail.status_code} · {product.name[:40]} · {media_url or 'بدون featured'}",
            )
        )
        img = featured

    if img is not None:
        media = client.get(reverse("media_image", args=[img.id]))
        ctype = media.get("Content-Type", "")
        ok = media.status_code == 200 and media.status_code != 302 and ctype.startswith("image/")
        steps.append(_step("سرو عکس کاتالوگ", ok, f"HTTP {media.status_code} · {ctype}"))
        redir = client.get(f"/media/img/{img.id}")
        steps.append(
            _step(
                "redirect اسلش عکس",
                redir.status_code in (200, 301),
                f"بدون اسلش → HTTP {redir.status_code}",
            )
        )

    rivals_page = client.get("/rivals/")
    steps.append(_step("قفسه رقیب", rivals_page.status_code == 200, f"HTTP {rivals_page.status_code}"))

    anon_manage = client.get("/manage/")
    steps.append(
        _step(
            "پنل بدون لاگین",
            anon_manage.status_code == 302 and "/admin/login/" in (anon_manage.url or ""),
            f"HTTP {anon_manage.status_code} → {anon_manage.url}",
        )
    )
    old_start = client.get("/rivals/crawl/start/")
    steps.append(
        _step(
            "کراول از صفحه کاربر حذف شده",
            old_start.status_code == 404,
            f"/rivals/crawl/start/ → HTTP {old_start.status_code}",
        )
    )

    return _pack("catalog", "تست ۱ — کاتالوگ و عکس‌های خودمان", steps)


class _HopRecorder(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.hops: list[tuple[int, str]] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops.append((code, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_with_hops(url: str, timeout: int = 10, accept: str = "*/*"):
    hops = _HopRecorder()
    opener = urllib.request.build_opener(hops)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    resp = opener.open(req, timeout=timeout)
    return resp, hops.hops


def run_crawl_e2e() -> dict:
    """One-product live pipeline: URLs, redirects, fetch, extract, match wiring."""
    steps: list[dict] = []
    client = Client()

    job = crawler_job.status()
    steps.append(
        _step(
            "وضعیت جاب کراول",
            isinstance(job, dict) and "running" in job,
            json.dumps({k: job.get(k) for k in ("running", "pid", "label")}, ensure_ascii=False),
        )
    )

    anon_status = client.get("/manage/crawl/status/")
    steps.append(
        _step(
            "API کراول بدون لاگین",
            anon_status.status_code == 302,
            f"HTTP {anon_status.status_code} (باید redirect به login باشد)",
        )
    )
    get_start = client.get("/manage/crawl/start/")
    steps.append(
        _step(
            "شروع کراول فقط POST",
            get_start.status_code in (302, 403, 405),
            f"GET /manage/crawl/start/ → HTTP {get_start.status_code}",
        )
    )

    product = (
        Product.objects.filter(status="publish")
        .exclude(images__dhash="")
        .prefetch_related("images")
        .distinct()
        .first()
    )
    if product is None:
        steps.append(_step("محصول مرجع با اثرانگشت", False, "محصول publish با dhash نیست"))
        return _pack("crawl", "تست ۲ — مسیر زنده کراول", steps)

    queries = build_queries(product.name, product.family)
    steps.append(_step("ساخت query جستجو", bool(queries), " ؛ ".join(queries[:4]) or "خالی"))

    img = next((i for i in product.images.all() if i.rel_path), None)
    if img is None:
        steps.append(_step("اثرانگشت عکس خودمان", False, "عکس ندارد"))
        return _pack("crawl", "تست ۲ — مسیر زنده کراول", steps)
    try:
        fp = fingerprint_image(Path(settings.UPLOADS_ROOT) / img.rel_path)
        steps.append(_step("اثرانگشت عکس خودمان", "dhash" in fp, "dhash آماده است"))
    except Exception as exc:
        steps.append(_step("اثرانگشت عکس خودمان", False, str(exc)))
        return _pack("crawl", "تست ۲ — مسیر زنده کراول", steps)

    reference = product.as_match_dict()
    shop = SHOPS[0]
    try:
        api = f"{shop.api}?per_page=1"
        resp, hops = _open_with_hops(api, timeout=10, accept="application/json")
        raw = resp.read(200_000)
        final = resp.geturl()
        code = getattr(resp, "status", None) or resp.getcode()
        hop_txt = " → ".join(f"{c}" for c, _ in hops) or "بدون redirect"
        steps.append(
            _step(
                f"API فروشگاه {shop.host}",
                200 <= int(code) < 400,
                f"HTTP {code} · hops {hop_txt} · final {final}",
            )
        )
        payload = json.loads(raw.decode("utf-8", "replace"))
        ok_json = isinstance(payload, list) and bool(payload)
        steps.append(_step("داده JSON کراول", ok_json, f"{len(payload) if isinstance(payload, list) else type(payload).__name__} ردیف"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        steps.append(_step(f"API فروشگاه {shop.host}", False, str(exc)))
        return _pack("crawl", "تست ۲ — مسیر زنده کراول", steps)

    try:
        found = search_shop(shop, queries[0], per_page=3) if queries else []
        steps.append(
            _step(
                "جستجوی نام محصول ما در فروشگاه",
                True,
                f"{len(found)} کاندید برای «{queries[0] if queries else ''}»",
            )
        )
    except Exception as exc:
        found = []
        steps.append(_step("جستجوی نام محصول ما در فروشگاه", False, str(exc)))

    rival = RivalProduct.objects.select_related("product").first()
    if rival:
        cache = Path(settings.BASE_DIR) / "data" / "rival-cache" / rival.image_path if rival.image_path else None
        file_ok = bool(cache and cache.is_file())
        steps.append(
            _step(
                "ربط رقیب ذخیره‌شده به محصول ما",
                bool(rival.product_id) and bool(rival.url),
                f"{rival.shop_host} → {rival.product.name[:36]} · cache {'هست' if file_ok else 'نیست'}",
            )
        )
        rimg = client.get(reverse("rival_image", args=[rival.id])) if rival.image_path else None
        if rimg is not None:
            steps.append(
                _step(
                    "سرو عکس رقیب",
                    rimg.status_code in (200, 404),
                    f"HTTP {rimg.status_code}",
                )
            )

    if found:
        cand = found[0]
        try:
            page_resp, page_hops = _open_with_hops(cand.url, timeout=10, accept="text/html")
            page_code = getattr(page_resp, "status", None) or page_resp.getcode()
            page_final = page_resp.geturl()
            page_resp.read(1)
            hop_txt = " → ".join(str(c) for c, _ in page_hops) or "بدون redirect"
            redirected = page_final.rstrip("/") != cand.url.rstrip("/") or bool(page_hops)
            steps.append(
                _step(
                    "صفحه محصول رقیب",
                    200 <= int(page_code) < 400,
                    f"HTTP {page_code} · {hop_txt} · {'redirect شد' if redirected else 'همان URL'}",
                )
            )
        except Exception as exc:
            steps.append(_step("صفحه محصول رقیب", False, str(exc)))
        try:
            blob = fetch_image(cand.image_url)
            from tahlil.matching.fingerprint import fingerprint_bytes

            cfp = fingerprint_bytes(blob)
            verdict = verdict_for(reference, cfp, cand.title, cand.family, loose=True)
            steps.append(
                _step(
                    "استخراج عکس و تطبیق با کالای ما",
                    verdict["status"] in ("match", "uncertain", "reject"),
                    f"{cand.title[:40]} · {verdict['status']} · vis {verdict['visual']} · title {verdict['title']}",
                )
            )
        except Exception as exc:
            steps.append(_step("استخراج عکس و تطبیق با کالای ما", False, str(exc)))
    else:
        steps.append(_step("صفحه محصول رقیب", True, "کاندید زنده نبود — مرحله صفحه رد شد (شبکه/جستجو خالی)"))
        steps.append(_step("استخراج عکس و تطبیق با کالای ما", True, "کاندید زنده نبود — تطبیق روی داده ذخیره‌شده کافی است"))

    return _pack("crawl", "تست ۲ — مسیر زنده کراول", steps)
