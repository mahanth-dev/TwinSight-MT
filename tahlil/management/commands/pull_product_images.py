"""Copy only our catalog product images from the WP backup tar.

Does not import MySQL / WooCommerce. Does not touch the TwinSight sqlite catalog.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tahlil.models import ProductImage

TAR_UPLOADS_PREFIX = (
    "backup-8.31.2026_11-41-18_asarehsp/homedir/public_html/wp-content/uploads/"
)


def find_backup_tar(base: Path) -> Path | None:
    env = os.environ.get("MT_BACKUP_TAR")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    for p in sorted(base.glob("backup-*asarehsp*.tar.gz")):
        if p.is_file():
            return p
    return None


class Command(BaseCommand):
    help = "Extract only catalog product images into data/uploads (no DB import)"

    def handle(self, *args, **opts):
        uploads = Path(settings.UPLOADS_ROOT)
        uploads.mkdir(parents=True, exist_ok=True)

        needed = sorted({rel for rel in ProductImage.objects.values_list("rel_path", flat=True) if rel})
        if not needed:
            raise CommandError(
                "در sqlite هیچ مسیر عکسی نیست. فایل data/mt_tahlil.sqlite3 باید از git باشد."
            )

        present = [rel for rel in needed if (uploads / rel).is_file()]
        missing = [rel for rel in needed if rel not in present]
        self.stdout.write(f"عکس کاتالوگ: {len(present)} موجود، {len(missing)} ناقص از {len(needed)}")
        if not missing:
            self.stdout.write(self.style.SUCCESS("همه عکس محصولات خودمان حاضر است."))
            return

        tar_path = find_backup_tar(Path(settings.BASE_DIR))
        if not tar_path:
            raise CommandError(
                "فایل backup-*asarehsp*.tar.gz در ریشه پروژه نیست. "
                "فقط همان tar را بگذار؛ SQL لازم نیست."
            )

        want = set(missing)
        copied = 0
        self.stdout.write(f"استخراج از {tar_path.name} …")
        with tarfile.open(tar_path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile() or not member.name.startswith(TAR_UPLOADS_PREFIX):
                    continue
                rel = member.name[len(TAR_UPLOADS_PREFIX) :]
                if rel not in want:
                    continue
                target = uploads / rel
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as out:
                    shutil.copyfileobj(extracted, out)
                copied += 1
                want.discard(rel)
                if not want:
                    break

        still = [rel for rel in missing if not (uploads / rel).is_file()]
        self.stdout.write(self.style.SUCCESS(f"+{copied} فایل کپی شد."))
        if still:
            self.stderr.write(self.style.WARNING(f"هنوز {len(still)} عکس در tar نبود."))
