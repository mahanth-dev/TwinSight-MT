"""Staff-only crawl console and end-to-end checks."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from tahlil import crawler_job
from tahlil.checks import run_catalog_e2e, run_crawl_e2e
from tahlil.crawl_ui import ALL_HOSTS, PRESETS, SOURCE_GROUPS
from tahlil.models import Product, RivalProduct

RESULTS_FILE = Path(settings.BASE_DIR) / "data" / "panel-tests.json"


def _read_results() -> dict:
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_results(payload: dict) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _families():
    return (
        Product.objects.filter(status="publish")
        .values("family", "family_label")
        .annotate(n=Count("id"))
        .order_by("family_label")
    )


@staff_member_required
@require_GET
def panel(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    hits = []
    if q:
        hits = list(
            Product.objects.filter(status="publish", name__icontains=q).order_by("name")[:12]
        )
    results = _read_results()
    return render(
        request,
        "manage/panel.html",
        {
            "crawl": crawler_job.status(),
            "log_text": crawler_job.log_text(),
            "families": _families(),
            "q": q,
            "hits": hits,
            "catalog_test": results.get("catalog"),
            "crawl_test": results.get("crawl"),
            "rival_count": RivalProduct.objects.count(),
            "presets": PRESETS,
            "source_groups": SOURCE_GROUPS,
            "crawl_events": crawler_job.events_tail(),
            "crawl_report": crawler_job.report(),
        },
    )


@staff_member_required
@require_POST
def crawl_start(request: HttpRequest) -> HttpResponse:
    preset_key = (request.POST.get("preset") or "custom").strip()
    preset = PRESETS.get(preset_key, {})

    product_id = (request.POST.get("product_id") or "").strip()

    if preset_key in PRESETS:
        shops = list(preset.get("shops") or [])
        no_html = bool(preset.get("no_html"))
        no_market = bool(preset.get("no_market"))
        loose = bool(preset.get("loose"))
        skip_done = bool(preset.get("skip_done"))
        pause = float(preset.get("pause") or 0.4)
        per_page = int(preset.get("per_page") or 8)
        mode_label = preset["label"]
        family = (request.POST.get("family") or "").strip()
        workers_n = max(1, min(3, int(preset.get("workers") or 1)))
        limit_n = int(preset.get("limit") or 20)
        if product_id:
            limit_n = 0
    else:
        shops = [h for h in request.POST.getlist("shop") if h in ALL_HOSTS]
        if not shops or set(shops) == set(ALL_HOSTS):
            shops = []
        no_html = False
        no_market = False
        loose = request.POST.get("loose") == "1"
        skip_done = request.POST.get("skip_done") == "1"
        try:
            pause = min(1.2, max(0.2, float(request.POST.get("pause") or 0.4)))
        except ValueError:
            pause = 0.4
        try:
            per_page = max(4, min(12, int(request.POST.get("per_page") or 8)))
        except ValueError:
            per_page = 8
        mode_label = "سفارشی"
        family = (request.POST.get("family") or "").strip()
        try:
            workers_n = max(1, min(3, int(request.POST.get("workers") or 1)))
        except ValueError:
            workers_n = 1
        limit_raw = (request.POST.get("limit") or "").strip()
        try:
            limit_n = int(limit_raw) if limit_raw else 0
        except ValueError:
            limit_n = 0
        if not product_id and not limit_n:
            limit_n = 20

    crawler_job.start(
        {
            "loose": loose,
            "skip_done": skip_done,
            "family": family,
            "product_id": product_id,
            "limit": limit_n,
            "workers": workers_n,
            "shops": shops,
            "no_html": no_html,
            "no_market": no_market,
            "pause": pause,
            "per_page": per_page,
            "mode_label": mode_label,
        }
    )
    return redirect("manage_panel")


@staff_member_required
@require_POST
def crawl_stop(request: HttpRequest) -> HttpResponse:
    crawler_job.stop()
    return redirect("manage_panel")


@staff_member_required
@require_GET
def crawl_status(request: HttpRequest) -> JsonResponse:
    data = crawler_job.status()
    data["log"] = crawler_job.log_text()
    return JsonResponse(data)


@staff_member_required
@require_POST
def run_test(request: HttpRequest) -> HttpResponse:
    which = request.POST.get("which") or ""
    stored = _read_results()
    if which == "catalog":
        stored["catalog"] = run_catalog_e2e()
    elif which == "crawl":
        stored["crawl"] = run_crawl_e2e()
    else:
        return redirect("manage_panel")
    _write_results(stored)
    return redirect(reverse("manage_panel") + f"#test-{which}")
