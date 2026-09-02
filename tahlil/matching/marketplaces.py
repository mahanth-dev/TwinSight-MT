"""Nationwide marketplaces. One query here reaches thousands of sellers at once.

Torob would be the obvious third one, but it answers every request from this
network with an arcaptcha wall (HTTP 490), page and API alike, so it is out.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .families import detect_family

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_JSON_BYTES = 3_000_000


@dataclass
class MarketCandidate:
    shop_host: str
    shop_name: str
    rival_ref: str
    title: str
    url: str
    price: str
    stock: str
    image_url: str
    query_used: str
    family: str
    family_label: str


def _get_json(url: str, timeout: int = 20):
    parts = urllib.parse.urlsplit(url)
    safe = urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            urllib.parse.quote(parts.path, safe="/%:@"),
            urllib.parse.quote(parts.query, safe="=&%:/,?"),
            "",
        )
    )
    req = urllib.request.Request(
        safe,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "fa-IR,fa;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(MAX_JSON_BYTES).decode("utf-8", "replace"))


def _rial_to_toman(value) -> str:
    """Both APIs quote Rial; the catalog is in Toman."""
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return ""
    if amount <= 0:
        return ""
    return str(amount // 10)


def _clean(title: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(title or "")).strip()


def search_digikala(query: str, limit: int = 12) -> list[MarketCandidate]:
    url = f"https://api.digikala.com/v1/search/?q={urllib.parse.quote(query)}&page=1"
    try:
        payload = _get_json(url)
    except Exception:
        return []
    rows = ((payload.get("data") or {}).get("products")) or []

    out: list[MarketCandidate] = []
    for row in rows[:limit]:
        title = _clean(row.get("title_fa"))
        uri = (row.get("url") or {}).get("uri") or ""
        images = ((row.get("images") or {}).get("main") or {}).get("url") or []
        image_url = images[0] if images else ""
        if not title or not uri or not image_url:
            continue
        variant = row.get("default_variant") or {}
        price = _rial_to_toman((variant.get("price") or {}).get("selling_price"))
        fam, fam_label = detect_family(title)
        out.append(
            MarketCandidate(
                shop_host="digikala.com",
                shop_name="دیجی‌کالا",
                rival_ref=str(row.get("id") or ""),
                title=title,
                url=urllib.parse.urljoin("https://www.digikala.com/", uri),
                price=price,
                stock="instock" if row.get("status") == "marketable" else "outofstock",
                image_url=image_url,
                query_used=query,
                family=fam,
                family_label=fam_label,
            )
        )
    return out


def search_basalam(query: str, limit: int = 12) -> list[MarketCandidate]:
    url = (
        "https://search.basalam.com/ai-engine/api/v2.0/product/search"
        f"?q={urllib.parse.quote(query)}"
    )
    try:
        payload = _get_json(url)
    except Exception:
        return []
    rows = payload.get("products") or []

    out: list[MarketCandidate] = []
    for row in rows[:limit]:
        title = _clean(row.get("name"))
        photo = row.get("photo") or {}
        image_url = photo.get("MEDIUM") or photo.get("SMALL") or ""
        pid = row.get("id")
        if not title or not image_url or not pid:
            continue
        fam, fam_label = detect_family(title)
        out.append(
            MarketCandidate(
                shop_host="basalam.com",
                shop_name="باسلام",
                rival_ref=str(pid),
                title=title,
                url=f"https://basalam.com/p/{pid}",
                price=_rial_to_toman(row.get("price")),
                stock="instock" if row.get("IsAvailable") else "outofstock",
                image_url=image_url,
                query_used=query,
                family=fam,
                family_label=fam_label,
            )
        )
    return out


MARKETS: dict[str, callable] = {
    "digikala.com": search_digikala,
    "basalam.com": search_basalam,
}


def collect_market_candidates(
    queries: list[str],
    markets: tuple[str, ...] = tuple(MARKETS),
    limit: int = 12,
    pause: float = 0.25,
) -> list[MarketCandidate]:
    seen: set[str] = set()
    found: list[MarketCandidate] = []
    for host in markets:
        search = MARKETS.get(host)
        if not search:
            continue
        for query in queries:
            for cand in search(query, limit=limit):
                if cand.url in seen:
                    continue
                seen.add(cand.url)
                found.append(cand)
            if pause:
                time.sleep(pause)
    return found
