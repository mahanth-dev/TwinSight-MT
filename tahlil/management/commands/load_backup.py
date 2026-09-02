"""Load Asareh WooCommerce backup into TwinSight."""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tahlil.matching.families import detect_family
from tahlil.matching.fingerprint import fingerprint_image
from tahlil.models import Product, ProductImage

THUMB_RE = re.compile(r"\((\d+),(\d+),'_thumbnail_id','(\d+)'\)")
FILE_RE = re.compile(r"\((\d+),(\d+),'_wp_attached_file','((?:\\'|[^'])*)'\)")
GALLERY_RE = re.compile(r"\((\d+),(\d+),'_product_image_gallery','([^']*)'\)")
AGENT_TOOLS = Path(
    "/home/asus/.cursor/projects/home-asus-project-asareh-new-vmt/agent-tools/"
    "9a89d61c-3186-4e1d-af03-09934ee9adb4.txt"
)


def unescape_sql(s: str) -> str:
    return s.replace("\\'", "'").replace("\\\\", "\\")


def pick_preview(original: Path) -> Path:
    stem, ext = original.stem, original.suffix
    parent = original.parent
    for suffix in ("-600x600", "-768x768", "-440x440", "-416x416", "-300x300"):
        cand = parent / f"{stem}{suffix}{ext}"
        if cand.exists():
            return cand
    return original


def rel_to_uploads(uploads: Path, path: Path) -> str:
    return str(path.resolve().relative_to(uploads.resolve()))


def load_core_from_agent_tools() -> list[dict]:
    snapshot = Path(settings.BASE_DIR) / "data" / "source_products.json"
    if snapshot.exists():
        return json.loads(snapshot.read_text(encoding="utf-8"))
    if not AGENT_TOOLS.exists():
        raise CommandError(
            "source_products.json و فایل agent-tools پیدا نشد. "
            "یک‌بار با همان بکاپ extract را اجرا کنید."
        )
    text = AGENT_TOOLS.read_text(encoding="utf-8")
    a = text.find("CATALOG_JSON_BEGIN\n")
    b = text.find("\nCATALOG_JSON_END")
    cat = json.loads(text[a + len("CATALOG_JSON_BEGIN\n") : b].strip())
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    return cat


def scan_postmeta(sql_path: Path) -> tuple[dict, dict, dict]:
    thumbs: dict[int, int] = {}
    files: dict[int, str] = {}
    galleries: dict[int, list[int]] = {}
    with sql_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if "_thumbnail_id" in line:
                for m in THUMB_RE.finditer(line):
                    thumbs[int(m.group(2))] = int(m.group(3))
            if "_wp_attached_file" in line:
                for m in FILE_RE.finditer(line):
                    files[int(m.group(2))] = unescape_sql(m.group(3))
            if "_product_image_gallery" in line:
                for m in GALLERY_RE.finditer(line):
                    ids = [int(x) for x in m.group(3).split(",") if x.strip().isdigit()]
                    if ids:
                        galleries[int(m.group(2))] = ids
    return thumbs, files, galleries


class Command(BaseCommand):
    help = "Import catalog + images from the Asareh cPanel backup"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        sql_path = Path(settings.SQL_PATH)
        uploads = Path(settings.UPLOADS_ROOT)
        if not sql_path.exists():
            raise CommandError(f"SQL not found: {sql_path}")
        if not uploads.exists():
            raise CommandError(f"uploads not found: {uploads}")

        if Product.objects.exists() and not opts["force"]:
            self.stdout.write(self.style.WARNING("کاتالوگ از قبل لود شده. برای از نو: --force"))
            return

        self.stdout.write("خواندن فهرست محصولات…")
        core = load_core_from_agent_tools()
        self.stdout.write(f"  {len(core)} محصول والد")

        self.stdout.write("اسکن postmeta برای عکس‌ها (چند ده ثانیه)…")
        thumbs, files, galleries = scan_postmeta(sql_path)
        self.stdout.write(f"  thumbnail={len(thumbs)} file={len(files)} gallery={len(galleries)}")

        if opts["force"]:
            Product.objects.all().delete()

        created = 0
        imaged = 0
        hashed = 0
        Path(settings.BASE_DIR, "data").mkdir(parents=True, exist_ok=True)

        with transaction.atomic():
            for row in core:
                fam, fam_label = detect_family(row.get("name") or "", row.get("cats") or "")
                slug = row.get("slug") or ""
                url = f"{settings.SITE_URL}/product/{slug}/" if slug else ""
                product = Product.objects.create(
                    wp_id=int(row["id"]),
                    name=row.get("name") or "",
                    slug=slug,
                    product_type=row.get("type") or "simple",
                    status=row.get("status") or "publish",
                    sku=row.get("sku") or "",
                    price=str(row.get("price") or ""),
                    price_max=str(row.get("price_max") or ""),
                    stock=row.get("stock") or "",
                    qty=str(row.get("qty") or ""),
                    variation_count=int(row.get("vars") or 0),
                    categories=row.get("cats") or "",
                    family=fam,
                    family_label=fam_label,
                    site_url=url,
                )
                created += 1
                pid = product.wp_id
                attach_ids: list[tuple[int, str]] = []
                if pid in thumbs:
                    attach_ids.append((thumbs[pid], "featured"))
                for gid in galleries.get(pid, [])[:3]:
                    if gid != thumbs.get(pid):
                        attach_ids.append((gid, "gallery"))

                for aid, role in attach_ids:
                    rel = files.get(aid)
                    if not rel:
                        continue
                    original = uploads / rel
                    if not original.exists():
                        continue
                    preview = pick_preview(original)
                    stored_rel = rel_to_uploads(uploads, preview)
                    dhash_hex = ""
                    hist: list[float] = []
                    try:
                        fp = fingerprint_image(preview)
                        dhash_hex = format(int(fp["dhash"]), "x")
                        hist = fp["hist"]
                        hashed += 1
                    except Exception as exc:
                        self.stderr.write(f"  hash fail {preview}: {exc}")
                    ProductImage.objects.create(
                        product=product,
                        rel_path=stored_rel,
                        role=role,
                        dhash=dhash_hex,
                        hist=hist,
                    )
                    imaged += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"تمام. محصول={created} ردیف‌عکس={imaged} هش‌شده={hashed}"
            )
        )
