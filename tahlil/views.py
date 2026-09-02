from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from tahlil import crawler_job
from tahlil.matching.fetch_page import fetch_bytes, parse_competitor_page
from tahlil.matching.fingerprint import fingerprint_bytes
from tahlil.matching.match import compare_pair, rank_catalog
from tahlil.models import CompetitorOffer, Product, ProductImage, RivalProduct


def _catalog_payload(qs=None) -> list[dict]:
    qs = qs if qs is not None else Product.objects.prefetch_related("images")
    return [p.as_match_dict() for p in qs]


def _fp_from_upload(request: HttpRequest):
    f = request.FILES.get("image")
    if not f:
        return None, "عکسی انتخاب نشده."
    data = f.read()
    if len(data) < 80:
        return None, "فایل تصویر خالی است."
    try:
        return fingerprint_bytes(data), ""
    except Exception as exc:
        return None, f"این فایل تصویر معتبر نیست: {exc}"


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    qs = Product.objects.all()
    published = qs.filter(status="publish")
    families = (
        published.values("family", "family_label")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return render(
        request,
        "tahlil/home.html",
        {
            "total": qs.count(),
            "published": published.count(),
            "with_image": Product.objects.filter(images__isnull=False).distinct().count(),
            "instock": published.filter(stock="instock").count(),
            "outofstock": published.filter(stock="outofstock").count(),
            "simple": published.filter(product_type="simple").count(),
            "variable": published.filter(product_type="variable").count(),
            "families": families,
            "rival_match": RivalProduct.objects.filter(verdict="match").count(),
            "rival_uncertain": RivalProduct.objects.filter(verdict="uncertain").count(),
            "rival_shops": RivalProduct.objects.values("shop_host").distinct().count(),
            "rival_covered": RivalProduct.objects.values("product").distinct().count(),
            "recent_rivals": RivalProduct.objects.select_related("product").filter(
                verdict="match"
            )[:6],
            "crawl": crawler_job.status(),
        },
    )


@require_GET
def product_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    family = (request.GET.get("family") or "").strip()
    status = request.GET.get("status") or "publish"
    stock = (request.GET.get("stock") or "").strip()
    ptype = (request.GET.get("type") or "").strip()

    qs = Product.objects.prefetch_related("images")
    if status != "all":
        qs = qs.filter(status=status)
    if family:
        qs = qs.filter(family=family)
    if stock:
        qs = qs.filter(stock=stock)
    if ptype:
        qs = qs.filter(product_type=ptype)
    if q:
        lookup = Q(name__icontains=q) | Q(sku__icontains=q) | Q(categories__icontains=q)
        if q.isdigit():
            lookup |= Q(wp_id=int(q))
        qs = qs.filter(lookup)

    families = (
        Product.objects.filter(status="publish")
        .values("family", "family_label")
        .annotate(n=Count("id"))
        .order_by("family_label")
    )
    return render(
        request,
        "tahlil/product_list.html",
        {
            "products": qs,
            "count": qs.count(),
            "q": q,
            "family": family,
            "status": status,
            "stock": stock,
            "ptype": ptype,
            "families": families,
        },
    )


@require_http_methods(["GET", "POST"])
def product_detail(request: HttpRequest, wp_id: int) -> HttpResponse:
    product = get_object_or_404(
        Product.objects.prefetch_related("images", "offers"), wp_id=wp_id
    )
    result = None
    error = ""
    rival_title = ""
    rival_url = ""
    rival_host = ""
    rival_price = ""

    if request.method == "POST":
        rival_title = (request.POST.get("rival_title") or "").strip()
        rival_url = (request.POST.get("rival_url") or "").strip()
        fp = None
        if rival_url:
            try:
                page = parse_competitor_page(rival_url)
                rival_title = rival_title or page["title"]
                rival_host = page["host"]
                rival_price = page["price_text"]
                if page["image_url"]:
                    fp = fingerprint_bytes(fetch_bytes(page["image_url"]))
                else:
                    error = "روی آن صفحه عکس محصول پیدا نشد."
            except Exception as exc:
                error = f"خواندن صفحه رقیب نشد: {exc}"
        if fp is None and not error:
            fp, error = _fp_from_upload(request)
        if fp and not error:
            result = compare_pair(product.as_match_dict(), fp, rival_title)
            if request.POST.get("save") == "1":
                CompetitorOffer.objects.create(
                    product=product,
                    source_name=rival_host or "آپلود دستی",
                    source_url=rival_url,
                    title=rival_title,
                    price_text=rival_price,
                    verdict=result["status"],
                    visual_score=result["visual"],
                    title_score=result["title"],
                    reasons=" | ".join(result["reasons"]),
                )
                return redirect("product_detail", wp_id=product.wp_id)

    return render(
        request,
        "tahlil/product_detail.html",
        {
            "product": product,
            "result": result,
            "error": error,
            "rival_title": rival_title,
            "rival_url": rival_url,
        },
    )


@require_http_methods(["GET", "POST"])
def compare_hub(request: HttpRequest) -> HttpResponse:
    error = ""
    ranked = None
    rival_title = ""
    rival_url = ""
    rival_host = ""
    saved = None

    if request.method == "POST":
        rival_title = (request.POST.get("rival_title") or "").strip()
        rival_url = (request.POST.get("rival_url") or "").strip()
        fp = None
        if rival_url:
            try:
                page = parse_competitor_page(rival_url)
                rival_title = rival_title or page["title"]
                rival_host = page["host"]
                if page["image_url"]:
                    fp = fingerprint_bytes(fetch_bytes(page["image_url"]))
                else:
                    error = "روی آن صفحه عکس محصول پیدا نشد."
            except Exception as exc:
                error = f"خواندن صفحه رقیب نشد: {exc}"
        if fp is None and not error:
            fp, error = _fp_from_upload(request)
        if fp and not error:
            published = Product.objects.filter(status="publish").prefetch_related("images")
            ranked = rank_catalog(_catalog_payload(published), fp, rival_title)
            if request.POST.get("save_top") == "1" and ranked["matches"]:
                top = ranked["matches"][0]
                prod = Product.objects.filter(wp_id=top["product_id"]).first()
                saved = CompetitorOffer.objects.create(
                    product=prod,
                    source_name=rival_host or "آپلود دستی",
                    source_url=rival_url,
                    title=rival_title,
                    verdict=top["status"],
                    visual_score=top["visual"],
                    title_score=top["title"],
                    reasons=" | ".join(top["reasons"]),
                )

    return render(
        request,
        "tahlil/compare.html",
        {
            "error": error,
            "ranked": ranked,
            "rival_title": rival_title,
            "rival_url": rival_url,
            "saved": saved,
        },
    )


@require_GET
def rival_list(request: HttpRequest) -> HttpResponse:
    verdict = request.GET.get("verdict") or "match"
    shop = (request.GET.get("shop") or "").strip()
    q = (request.GET.get("q") or "").strip()
    cheaper = request.GET.get("cheaper") == "1"

    qs = RivalProduct.objects.select_related("product")
    if verdict != "all":
        qs = qs.filter(verdict=verdict)
    if shop:
        qs = qs.filter(shop_host=shop)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(product__name__icontains=q))
    qs = qs.order_by("verdict", "-visual_score", "-title_score")

    rows = list(qs[:400])
    if cheaper:
        rows = [r for r in rows if r.cheaper_than_us]

    shops = (
        RivalProduct.objects.values("shop_host", "shop_name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return render(
        request,
        "tahlil/rival_list.html",
        {
            "rows": rows,
            "count": len(rows),
            "total_rows": RivalProduct.objects.count(),
            "verdict": verdict,
            "shop": shop,
            "q": q,
            "cheaper": cheaper,
            "shops": shops,
            "total_match": RivalProduct.objects.filter(verdict="match").count(),
            "total_uncertain": RivalProduct.objects.filter(verdict="uncertain").count(),
            "covered": RivalProduct.objects.values("product").distinct().count(),
            "crawl": crawler_job.status(),
            "families": Product.objects.filter(status="publish")
            .values("family", "family_label")
            .annotate(n=Count("id"))
            .order_by("family_label"),
        },
    )


@require_POST
def crawl_start(request: HttpRequest) -> HttpResponse:
    limit = request.POST.get("limit") or ""
    workers = request.POST.get("workers") or "2"
    try:
        limit_n = int(limit) if limit.strip() else 0
    except ValueError:
        limit_n = 0
    try:
        workers_n = max(1, min(4, int(workers)))
    except ValueError:
        workers_n = 2
    product_id = (request.POST.get("product_id") or "").strip()
    if not product_id and not limit_n:
        limit_n = 500
    crawler_job.start(
        {
            "loose": request.POST.get("loose") == "1",
            "skip_done": request.POST.get("skip_done") == "1",
            "family": (request.POST.get("family") or "").strip(),
            "product_id": product_id,
            "limit": limit_n,
            "workers": workers_n,
        }
    )
    nxt = request.POST.get("next") or reverse("rival_list")
    return redirect(nxt)


@require_POST
def crawl_stop(request: HttpRequest) -> HttpResponse:
    crawler_job.stop()
    nxt = request.POST.get("next") or reverse("rival_list")
    return redirect(nxt)


@require_GET
def crawl_status(request: HttpRequest) -> JsonResponse:
    return JsonResponse(crawler_job.status())


@require_GET
def rival_image(request: HttpRequest, rival_id: int) -> FileResponse:
    rival = get_object_or_404(RivalProduct, pk=rival_id)
    if not rival.image_path:
        raise Http404()
    root = (Path(settings.BASE_DIR) / "data" / "rival-cache").resolve()
    path = (root / rival.image_path).resolve()
    if root not in path.parents or not path.is_file():
        raise Http404()
    return FileResponse(path.open("rb"), content_type="image/jpeg")


@require_GET
def media_image(request: HttpRequest, image_id: int) -> FileResponse:
    img = get_object_or_404(ProductImage, pk=image_id)
    root = Path(settings.UPLOADS_ROOT).resolve()
    path = (root / img.rel_path).resolve()
    if root not in path.parents and path != root:
        raise Http404()
    if not path.is_file():
        raise Http404()
    return FileResponse(path.open("rb"), content_type="image/webp")
