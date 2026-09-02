"""Re-judge stored rivals after the matching rule changes. No network needed."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from tahlil.matching.families import detect_family, families_conflict, spec_relation
from tahlil.matching.match import decide
from tahlil.models import RivalProduct


class Command(BaseCommand):
    help = "Recompute verdicts for rivals already stored"

    def add_arguments(self, parser):
        parser.add_argument(
            "--drop-rejected",
            action="store_true",
            help="delete rows the new rule refuses",
        )
        parser.add_argument(
            "--loose",
            action="store_true",
            help="judge with the low-sensitivity rule",
        )

    def handle(self, *args, **opts):
        rows = list(RivalProduct.objects.select_related("product"))
        changed = 0
        counts = {"match": 0, "uncertain": 0, "reject": 0}
        doomed: list[int] = []

        with transaction.atomic():
            for row in rows:
                our_title = row.product.name if row.product else ""
                their_family, _ = detect_family(row.title)
                fam_clash = families_conflict(
                    (row.product.family if row.product else "other") or "other",
                    their_family,
                )
                status, reasons = decide(
                    row.visual_score,
                    row.title_score,
                    fam_clash,
                    spec_relation(our_title, row.title),
                    loose=opts["loose"],
                )
                counts[status] += 1
                if status == "reject":
                    doomed.append(row.id)
                if status != row.verdict:
                    changed += 1
                    if status != "reject":
                        row.verdict = status
                        row.reasons = " | ".join(reasons)
                        row.save(update_fields=["verdict", "reasons"])

            if opts["drop_rejected"] and doomed:
                RivalProduct.objects.filter(id__in=doomed).delete()

        self.stdout.write(
            f"بازبینی {len(rows)} ردیف → match {counts['match']} / "
            f"مشکوک {counts['uncertain']} / ردشده {counts['reject']} "
            f"({changed} تغییر حکم)"
        )
        if doomed and not opts["drop_rejected"]:
            self.stdout.write("برای پاک کردن ردشده‌ها: --drop-rejected")
