"""Fetch a public competitor product/listing page and pull title + images."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_BYTES = 2_000_000
MAX_ITEMS = 24


class _ImgTitleParser(HTMLParser):
    def __init__(self, base: str):
        super().__init__()
        self.base = base
        self.og_title = ""
        self.og_image = ""
        self.page_title = ""
        self._in_title = False
        self.images: list[str] = []
        self.json_ld: list[dict] = []
        self._in_ld = False
        self._ld_buf: list[str] = []
        self.cards: list[dict] = []  # listing cards
        self._card: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            prop = a.get("property") or a.get("name") or ""
            content = a.get("content") or ""
            if prop in ("og:title", "twitter:title") and content and not self.og_title:
                self.og_title = content
            if prop in ("og:image", "twitter:image") and content and not self.og_image:
                self.og_image = urljoin(self.base, content)
        elif tag == "title":
            self._in_title = True
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-large_image") or ""
            if src.startswith("data:"):
                return
            if src:
                self.images.append(urljoin(self.base, src))
        elif tag == "script" and "ld+json" in (a.get("type") or ""):
            self._in_ld = True
            self._ld_buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            raw = "".join(self._ld_buf).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return
            if isinstance(data, list):
                self.json_ld.extend([x for x in data if isinstance(x, dict)])
            elif isinstance(data, dict):
                self.json_ld.append(data)

    def handle_data(self, data):
        if self._in_title:
            self.page_title += data
        if self._in_ld:
            self._ld_buf.append(data)


def _host_is_public(host: str) -> bool:
    host = host.strip().strip("[]")
    if not host or host.lower() in {"localhost"}:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def fetch_html(url: str, timeout: int = 14) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("فقط http/https")
    if not parsed.hostname or not _host_is_public(parsed.hostname):
        raise ValueError("آدرس مجاز نیست")
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(req, timeout=timeout) as resp:
        final = resp.geturl()
        data = resp.read(MAX_BYTES)
    return data.decode("utf-8", "replace"), final


def fetch_bytes(url: str, timeout: int = 14) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("فقط http/https")
    if not parsed.hostname or not _host_is_public(parsed.hostname):
        raise ValueError("آدرس مجاز نیست")
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_BYTES)


def _product_from_ld(blocks: list[dict], base: str) -> dict | None:
    def walk(obj):
        if isinstance(obj, list):
            for x in obj:
                got = walk(x)
                if got:
                    return got
        if isinstance(obj, dict):
            t = obj.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return obj
            if "@graph" in obj:
                return walk(obj["@graph"])
        return None

    prod = walk(blocks)
    if not prod:
        return None
    img = prod.get("image")
    if isinstance(img, list) and img:
        img = img[0]
    if isinstance(img, dict):
        img = img.get("url")
    offers = prod.get("offers") or {}
    if isinstance(offers, list) and offers:
        offers = offers[0]
    price = ""
    if isinstance(offers, dict):
        price = str(offers.get("price") or offers.get("lowPrice") or "")
    return {
        "title": prod.get("name") or "",
        "image": urljoin(base, img) if img else "",
        "price": price,
        "url": prod.get("url") or "",
    }


def parse_competitor_page(url: str) -> dict:
    html, final = fetch_html(url)
    parser = _ImgTitleParser(final)
    try:
        parser.feed(html)
    except Exception:
        pass
    ld = _product_from_ld(parser.json_ld, final)
    title = (ld or {}).get("title") or parser.og_title or parser.page_title.strip()
    image = (ld or {}).get("image") or parser.og_image
    if not image:
        for src in parser.images:
            if any(x in src.lower() for x in ("logo", "icon", "sprite", "placeholder", "1x1")):
                continue
            image = src
            break
    price = (ld or {}).get("price") or ""
    host = urlparse(final).hostname or ""
    return {
        "url": final,
        "host": host,
        "title": re.sub(r"\s+", " ", title or "").strip(),
        "image_url": image or "",
        "price_text": price,
        "error": "",
    }
