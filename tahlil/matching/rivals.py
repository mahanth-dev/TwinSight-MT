"""Crawl competitor shops for products that look like ours.

Only the WooCommerce Store API is used — a public, unauthenticated read endpoint
that these shops expose for their own storefront. One product of ours acts as the
reference; candidates are accepted on image similarity first, then product family,
then title overlap.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .families import detect_family, families_conflict, normalize, title_tokens
from .html_shop import HTML_SHOPS, HtmlShop, collect_html_candidates
from .marketplaces import MARKETS, collect_market_candidates

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_JSON_BYTES = 1_500_000
MAX_IMAGE_BYTES = 1_500_000


@dataclass(frozen=True)
class RivalShop:
    host: str
    name: str

    @property
    def api(self) -> str:
        return f"https://{self.host}/wp-json/wc/store/v1/products"


# Verified 1 Sep 2026: these hosts answer /wp-json/wc/store/v1/products with JSON.
SHOPS: tuple[RivalShop, ...] = (
    RivalShop("gishasport.com", "گیشا اسپرت"),
    RivalShop("takrazm.com", "تک رزم"),
    RivalShop("pooyasport.com", "پویا اسپرت"),
    RivalShop("topsportgym.com", "تاپ اسپرت"),
    RivalShop("kalavarzesh.com", "کالاورزش"),
    RivalShop("onesport.ir", "وان اسپورت"),
    RivalShop("safirsport.com", "سفیر اسپرت"),
    RivalShop("shahrevarzesh.com", "شهر ورزش"),
    RivalShop("sportbazan.com", "اسپرت بازان"),
)

SHOPS_BY_HOST = {s.host: s for s in SHOPS}

# Words that describe the product kind — a query without one of these is too vague.
FAMILY_QUERY_HINT = {
    "yoga": "مت یوگا",
    "dart": "دارت",
    "table-tennis": "پینگ پنگ",
    "racket": "راکت",
    "ball": "توپ",
    "swim": "شنا",
    "bottle": "شیکر",
    "glove": "دستکش",
    "shoe": "کفش",
    "bag": "کوله",
    "sock": "جوراب",
    "cap": "کلاه",
    "apparel-set": "ست ورزشی",
    "apparel": "تیشرت",
    "fitness": "بدنسازی",
    "accessory": "",
    "other": "",
}


def _ordered_tokens(name: str) -> list[str]:
    """Distinctive tokens in the order they appear in the title."""
    keep = title_tokens(name)
    out: list[str] = []
    for tok in normalize(name).split():
        if tok in keep and tok not in out:
            out.append(tok)
    return out


def build_queries(name: str, family: str) -> list[str]:
    """Two or three short search strings, built from the product's own words.

    The family hint is a last resort only: asking for «مت یوگا» because a
    pilates band happens to sit in the yoga family returns mats, not bands.
    """
    tokens = _ordered_tokens(name)
    if not tokens:
        return []
    latin = [t for t in tokens if t.isascii() and any(c.isalpha() for c in t)]
    persian = [t for t in tokens if t not in latin]
    hint = FAMILY_QUERY_HINT.get(family, "")

    queries: list[str] = []

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", q).strip()
        if len(q) >= 3 and q not in queries:
            queries.append(q)

    brand = max(latin, key=len) if latin else ""
    if len(brand) < 3:
        brand = ""

    if len(persian) >= 2:
        add(" ".join(persian[:2]))
    if brand:
        add(f"{persian[0]} {brand}" if persian else brand)
    if len(persian) >= 3:
        add(" ".join(persian[:3]))
    elif persian and not queries:
        add(f"{hint} {persian[0]}" if hint else persian[0])
    if not queries and hint:
        add(hint)
    return queries[:3]


def encode_url(url: str) -> str:
    """Percent-encode non-ASCII path/query bits — these shops serve Persian filenames."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc.encode("idna").decode("ascii") if parts.netloc else "",
            urllib.parse.quote(parts.path, safe="/%:@"),
            urllib.parse.quote(parts.query, safe="=&%:/,?"),
            "",
        )
    )


def _get_json(url: str, timeout: int = 15):
    req = urllib.request.Request(
        encode_url(url), headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(MAX_JSON_BYTES).decode("utf-8", "replace"))


def fetch_image(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(
        encode_url(url), headers={"User-Agent": USER_AGENT, "Accept": "image/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_IMAGE_BYTES)


def _pick_image(images: list[dict]) -> str:
    """Prefer a mid-size variant: big enough to hash, small enough to download fast."""
    if not images:
        return ""
    img = images[0]
    srcset = img.get("srcset") or ""
    best_url, best_w = "", 0
    for part in srcset.split(","):
        bits = part.strip().split()
        if len(bits) != 2 or not bits[1].endswith("w"):
            continue
        try:
            width = int(bits[1][:-1])
        except ValueError:
            continue
        if 300 <= width <= 800 and width > best_w:
            best_url, best_w = bits[0], width
    return best_url or img.get("src") or img.get("thumbnail") or ""


def _price_text(prices: dict) -> tuple[str, str]:
    if not prices:
        return "", ""
    raw = prices.get("price") or prices.get("regular_price") or ""
    minor = prices.get("currency_minor_unit")
    currency = prices.get("currency_code") or ""
    if raw and isinstance(minor, int) and minor > 0:
        try:
            raw = str(int(int(raw) / (10**minor)))
        except (TypeError, ValueError):
            pass
    return str(raw or ""), currency


@dataclass
class Candidate:
    shop_host: str
    shop_name: str
    rival_ref: str
    title: str
    url: str
    price: str
    currency: str
    stock: str
    image_url: str
    query_used: str
    family: str = "other"
    family_label: str = ""
    image_bytes: bytes | None = field(default=None, repr=False)


def search_shop(shop: RivalShop, query: str, per_page: int = 10) -> list[Candidate]:
    params = urllib.parse.urlencode({"search": query, "per_page": per_page})
    try:
        data = _get_json(f"{shop.api}?{params}")
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    out: list[Candidate] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        title = html.unescape((row.get("name") or "").strip())
        url = row.get("permalink") or ""
        if not title or not url:
            continue
        image_url = _pick_image(row.get("images") or [])
        if not image_url:
            continue
        price, currency = _price_text(row.get("prices") or {})
        fam, fam_label = detect_family(title)
        out.append(
            Candidate(
                shop_host=shop.host,
                shop_name=shop.name,
                rival_ref=str(row.get("id") or ""),
                title=title,
                url=url,
                price=price,
                currency=currency,
                stock="instock" if row.get("is_in_stock") else "outofstock",
                image_url=image_url,
                query_used=query,
                family=fam,
                family_label=fam_label,
            )
        )
    return out


def collect_candidates(
    queries: list[str],
    shops: tuple[RivalShop, ...] = SHOPS,
    per_page: int = 10,
    pause: float = 0.25,
    our_family: str = "other",
    max_candidates: int = 30,
) -> list[Candidate]:
    """Run every query against every shop, de-duplicated by product URL.

    Listings whose own title says they are a different kind of goods are dropped
    before their image is downloaded — the verdict step would reject them anyway.
    """
    seen: set[str] = set()
    found: list[Candidate] = []
    for shop in shops:
        for query in queries:
            for cand in search_shop(shop, query, per_page=per_page):
                if cand.url in seen:
                    continue
                seen.add(cand.url)
                if families_conflict(our_family, cand.family):
                    continue
                found.append(cand)
            if pause:
                time.sleep(pause)
    return found[:max_candidates]


def collect_all_candidates(
    queries: list[str],
    shops: tuple[RivalShop, ...] = SHOPS,
    html_shops: tuple[HtmlShop, ...] = HTML_SHOPS,
    markets: tuple[str, ...] = tuple(MARKETS),
    per_page: int = 10,
    pause: float = 0.25,
    our_family: str = "other",
    max_candidates: int = 30,
) -> list[Candidate]:
    """Shops with an API, shops read as pages, and the big marketplaces."""
    found = collect_candidates(
        queries,
        shops=shops,
        per_page=per_page,
        pause=pause,
        our_family=our_family,
        max_candidates=max_candidates,
    )
    seen = {c.url for c in found}

    def absorb(raw, rival_ref: str = "", stock: str = "") -> None:
        if raw.url in seen:
            return
        seen.add(raw.url)
        if families_conflict(our_family, raw.family):
            return
        found.append(
            Candidate(
                shop_host=raw.shop_host,
                shop_name=raw.shop_name,
                rival_ref=rival_ref,
                title=raw.title,
                url=raw.url,
                price=raw.price,
                currency="",
                stock=stock,
                image_url=raw.image_url,
                query_used=raw.query_used,
                family=raw.family,
                family_label=raw.family_label,
            )
        )

    if html_shops:
        for raw in collect_html_candidates(
            queries, shops=html_shops, limit=per_page, pause=pause
        ):
            absorb(raw)

    if markets:
        for raw in collect_market_candidates(
            queries, markets=markets, limit=per_page, pause=pause
        ):
            absorb(raw, rival_ref=raw.rival_ref, stock=raw.stock)

    return found
