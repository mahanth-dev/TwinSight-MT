"""Read shops that expose no product API by parsing their public search page.

Same thing a visitor's browser receives: the search results page, then the
product cards inside it (link, photo, title, price when it is printed on the card).
"""

from __future__ import annotations

import html as html_mod
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

from .families import detect_family

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_HTML_BYTES = 1_800_000
# One number only; spaces inside the number would glue a product code onto it.
# Out-of-stock cards print "0 تومان", so short numbers must be caught here too
# rather than skipped — otherwise the next card's price gets picked up.
PRICE_RE = re.compile(
    r"([\d\u06f0-\u06f9][\d\u06f0-\u06f9.,\u066c]*)[\s\u200c]{0,40}"
    r"(?:تومان|ریال|ريال)"
)
TAG_RE = re.compile(r"<[^>]+>")
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

# Storefront titles carry SEO furniture. Strip it so title scoring stays honest.
TITLE_NOISE = (
    "خرید اینترنتی",
    "فروشگاه اینترنتی",
    "فروشگاه ورزشی",
    "لوازم ورزشی",
    "قیمت",
    "ارسال رایگان",
    "فروشگاه",
    "خرید",
)


def clean_title(raw: str) -> str:
    text = re.sub(r"\s+", " ", html_mod.unescape(raw or "")).strip()
    if not text:
        return ""
    segments = []
    for part in re.split(r"[|｜»]", text):
        part = part.strip(" -–—/\\،")
        if part:
            noise = sum(1 for n in TITLE_NOISE if n in part)
            segments.append((noise, -len(part), part))
    if segments:
        segments.sort()
        text = segments[0][2]
    for prefix in ("خرید اینترنتی ", "خرید و قیمت ", "خرید ", "قیمت "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = re.split(r"\s*/\s*(?=فروشگاه|لوازم|خرید)", text)[0]
    return text.strip(" -–—/\\،")


@dataclass(frozen=True)
class HtmlShop:
    host: str
    name: str
    search_template: str
    product_pattern: str

    def search_url(self, query: str) -> str:
        return self.search_template.format(q=urllib.parse.quote(query))


# Verified 1 Sep 2026. Both run PrestaShop, whose search page is server-rendered.
HTML_SHOPS: tuple[HtmlShop, ...] = (
    HtmlShop(
        "anik.ir",
        "ورزشی فروشی",
        "https://anik.ir/search?controller=search&s={q}",
        r"^https?://(?:www\.)?anik\.ir/[^/]+/\d+-[^/]+\.html$",
    ),
    HtmlShop(
        "allsport.ir",
        "آل اسپرت",
        "https://allsport.ir/search?controller=search&s={q}",
        r"^https?://(?:www\.)?allsport\.ir/[^/]+/\d+-[^/]+\.html$",
    ),
)

HTML_SHOPS_BY_HOST = {s.host: s for s in HTML_SHOPS}


def encode_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            urllib.parse.quote(parts.path, safe="/%:@"),
            urllib.parse.quote(parts.query, safe="=&%:/,?"),
            "",
        )
    )


def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        encode_url(url),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_HTML_BYTES).decode("utf-8", "replace")


def _best_srcset(value: str) -> str:
    best_url, best_w = "", 0
    for part in value.split(","):
        bits = part.strip().split()
        if len(bits) != 2 or not bits[1].endswith("w"):
            continue
        try:
            width = int(bits[1][:-1])
        except ValueError:
            continue
        if 250 <= width <= 900 and width > best_w:
            best_url, best_w = bits[0], width
    return best_url


class _CardParser(HTMLParser):
    """Collect (href → image, titles) for every anchor that wraps or labels a product."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.images: dict[str, str] = {}
        self.titles: dict[str, list[str]] = {}
        self._stack: list[str] = []

    def _add_title(self, href: str, text: str) -> None:
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if len(text) >= 4:
            self.titles.setdefault(href, []).append(text)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a":
            href = a.get("href") or ""
            full = urllib.parse.urljoin(self.base, href).split("#")[0]
            self._stack.append(full)
            self._add_title(full, a.get("title"))
        elif tag == "img" and self._stack:
            href = self._stack[-1]
            self._add_title(href, a.get("alt"))
            if href in self.images:
                return
            src = (
                _best_srcset(a.get("srcset") or a.get("data-srcset") or "")
                or a.get("src")
                or a.get("data-src")
                or a.get("data-original")
                or a.get("data-lazy-src")
                or ""
            )
            if src and not src.startswith("data:"):
                self.images[href] = urllib.parse.urljoin(self.base, src)

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._stack:
            self._add_title(self._stack[-1], data)


def _price_near(page: str, href: str) -> str:
    """Cards print the price beside the link, usually split across several tags."""
    needle = href.split("://", 1)[-1]
    idx = page.find(needle)
    if idx < 0:
        needle = href.rstrip("/").rsplit("/", 1)[-1]
        idx = page.find(needle)
        if idx < 0:
            return ""
    # Markup between the title and the price is mostly blanks once tags are
    # dropped, so collapse first and only then take a short window.
    text = re.sub(r"\s+", " ", TAG_RE.sub(" ", page[idx : idx + 14000]))
    match = PRICE_RE.search(text[:420])
    if not match:
        return ""
    digits = re.sub(r"[^\d]", "", match.group(1).translate(FA_DIGITS)).lstrip("0")
    return digits if 4 <= len(digits) <= 12 else ""


@dataclass
class HtmlCandidate:
    shop_host: str
    shop_name: str
    title: str
    url: str
    price: str
    image_url: str
    query_used: str
    family: str
    family_label: str


def search_html_shop(shop: HtmlShop, query: str, limit: int = 12) -> list[HtmlCandidate]:
    try:
        page = fetch_text(shop.search_url(query))
    except Exception:
        return []

    parser = _CardParser(f"https://{shop.host}/")
    try:
        parser.feed(page)
    except Exception:
        pass

    pattern = re.compile(shop.product_pattern)
    out: list[HtmlCandidate] = []
    for href, image_url in parser.images.items():
        if not pattern.match(href):
            continue
        titles = parser.titles.get(href) or []
        title = clean_title(max(titles, key=len)) if titles else ""
        if len(title) < 4:
            continue
        fam, fam_label = detect_family(title)
        out.append(
            HtmlCandidate(
                shop_host=shop.host,
                shop_name=shop.name,
                title=title,
                url=href,
                price=_price_near(page, href),
                image_url=image_url,
                query_used=query,
                family=fam,
                family_label=fam_label,
            )
        )
        if len(out) >= limit:
            break
    return out


def collect_html_candidates(
    queries: list[str],
    shops: tuple[HtmlShop, ...] = HTML_SHOPS,
    limit: int = 12,
    pause: float = 0.3,
) -> list[HtmlCandidate]:
    seen: set[str] = set()
    found: list[HtmlCandidate] = []
    for shop in shops:
        for query in queries:
            for cand in search_html_shop(shop, query, limit=limit):
                if cand.url in seen:
                    continue
                seen.add(cand.url)
                found.append(cand)
            if pause:
                time.sleep(pause)
    return found
