"""Strict match verdicts: never present a weak lookalike as the same product."""

from __future__ import annotations

from .families import detect_family, families_conflict, spec_relation, title_score
from .fingerprint import visual_score as vscore


def decide(
    visual: float,
    tscore: float,
    family_conflict: bool,
    spec_state: bool | str,
    has_title: bool = True,
    loose: bool = False,
) -> tuple[str, list[str]]:
    """Studio photos of unrelated goods look alike, so a photo alone never wins.

    A verdict of "match" needs the picture *and* the words to agree, and it is
    refused outright when the two titles name different models or sizes.

    `loose` only widens what is kept as "شبیه" for browsing; the bar for a
    confident match is identical in both modes.
    """
    if isinstance(spec_state, bool):
        spec_state = "clash" if spec_state else "ok"

    if family_conflict:
        return "reject", ["نوع کالا فرق دارد."]

    if spec_state == "clash":
        if visual >= 0.9:
            return "uncertain", ["عکس شبیه است ولی مدل/سایز در عنوان یکی نیست."]
        if loose and visual >= 0.75 and tscore >= 0.15:
            return "uncertain", ["مدل فرق دارد؛ فقط برای مقایسهٔ قیمت."]
        return "reject", ["مدل یا سایز در عنوان فرق دارد."]

    if spec_state == "thin" and has_title:
        if visual >= 0.93 and tscore >= 0.45:
            return "match", ["عکس تقریباً یکی است و عنوان تناقضی ندارد."]
        if visual >= 0.80 and tscore >= 0.30:
            return "uncertain", ["یک طرف کد/مدل دارد و طرف دیگر ندارد."]
        if loose and ((visual >= 0.70 and tscore >= 0.12) or tscore >= 0.40):
            return "uncertain", ["از خانوادهٔ همین کالا، مدلش قابل تأیید نیست."]
        return "reject", ["مدل کالا در دو عنوان قابل تطبیق نیست."]

    if not has_title:
        if visual >= 0.97:
            return "match", ["عکس عملاً همان فایل است."]
        if visual >= 0.85 or (loose and visual >= 0.65):
            return "uncertain", ["فقط عکس داریم؛ برای حکم قطعی کافی نیست."]
        return "reject", ["عکس به‌اندازهٔ کافی شبیه نیست."]

    if visual >= 0.985 and tscore >= 0.15:
        return "match", ["عکس همان فایل است و عنوان تناقضی ندارد."]
    if visual >= 0.93 and tscore >= 0.30:
        return "match", ["عکس تقریباً یکی است و عنوان هم می‌خواند."]
    if visual >= 0.86 and tscore >= 0.42:
        return "match", ["عکس خیلی نزدیک و عنوان به‌اندازهٔ کافی مشترک است."]
    if visual >= 0.80 and tscore >= 0.55:
        return "match", ["عنوان تقریباً یکی است و عکس هم نزدیک است."]

    if visual >= 0.86 and tscore >= 0.12:
        return "uncertain", ["عکس نزدیک است اما عنوان کم می‌آورد."]
    if visual >= 0.78 and tscore >= 0.30:
        return "uncertain", ["شبیه است، برای «همین کالا» قطعی نیست."]
    if visual >= 0.72 and tscore >= 0.45:
        return "uncertain", ["عنوان شبیه است اما عکس یکی نیست."]

    # Loose mode still needs the words to say something; a lookalike photo with
    # nothing in common in the title is noise, not data.
    if loose:
        if tscore >= 0.45:
            return "uncertain", ["عنوان خیلی نزدیک است، عکسشان فرق دارد."]
        if visual >= 0.70 and tscore >= 0.15:
            return "uncertain", ["شباهت متوسط؛ برای مرور قیمت نگه داشته شد."]
        if visual >= 0.62 and tscore >= 0.28:
            return "uncertain", ["هم‌خانواده و نسبتاً شبیه."]

    if visual < 0.72:
        return "reject", ["عکس به‌اندازهٔ کافی شبیه نیست."]
    return "reject", ["شباهت کلی، نه همان محصول."]


def verdict_for(
    product: dict,
    query_fp: dict,
    query_title: str,
    query_family: str | None = None,
    loose: bool = False,
) -> dict:
    visuals = [vscore(query_fp, fp) for fp in (product.get("fingerprints") or [])]
    visual = max(visuals) if visuals else 0.0

    our_title = product.get("name") or ""
    tscore = title_score(our_title, query_title) if query_title else 0.0

    our_fam = product.get("family") or "other"
    if not query_family:
        query_family, _ = detect_family(query_title or "", "")
    conflict = families_conflict(our_fam, query_family)
    spec_state = spec_relation(our_title, query_title) if query_title else "ok"

    status, reason = decide(
        visual, tscore, conflict, spec_state, has_title=bool(query_title), loose=loose
    )

    combined = 0.62 * visual + 0.38 * (tscore if query_title else visual)
    if conflict or spec_state == "clash":
        combined *= 0.35

    return {
        "product_id": product["id"],
        "name": our_title,
        "status": status,
        "visual": round(visual, 4),
        "title": round(tscore, 4),
        "combined": round(combined, 4),
        "family": our_fam,
        "family_label": product.get("family_label") or "",
        "conflict": conflict,
        "spec_state": spec_state,
        "reasons": reason,
        "price": product.get("price") or "",
        "price_max": product.get("price_max") or "",
        "sku": product.get("sku") or "",
        "stock": product.get("stock") or "",
        "url": product.get("url") or "",
        "has_image": bool(product.get("images")),
    }


def rank_catalog(products: list[dict], query_fp: dict, query_title: str) -> dict:
    q_fam, q_fam_label = detect_family(query_title or "", "")
    scored = [
        verdict_for(p, query_fp, query_title, q_fam)
        for p in products
        if p.get("fingerprints")
    ]
    matches = [x for x in scored if x["status"] == "match"]
    uncertain = [x for x in scored if x["status"] == "uncertain"]
    matches.sort(key=lambda x: (x["combined"], x["visual"], x["title"]), reverse=True)
    uncertain.sort(key=lambda x: (x["combined"], x["visual"]), reverse=True)
    return {
        "query_family": q_fam,
        "query_family_label": q_fam_label,
        "matches": matches[:12],
        "uncertain": uncertain[:6],
        "match_count": len(matches),
        "uncertain_count": len(uncertain),
    }


def compare_pair(product: dict, query_fp: dict, query_title: str) -> dict:
    q_fam, q_fam_label = detect_family(query_title or "", "")
    v = verdict_for(product, query_fp, query_title, q_fam)
    v["query_family"] = q_fam
    v["query_family_label"] = q_fam_label
    return v
