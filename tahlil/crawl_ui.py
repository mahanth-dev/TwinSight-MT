"""Named crawl presets and source copy for the staff panel."""

from __future__ import annotations

from tahlil.matching.html_shop import HTML_SHOPS
from tahlil.matching.rivals import SHOPS

PRESETS: dict[str, dict] = {
    "light": {
        "label": "آزمایش سبک",
        "blurb": "۵ کالای خودمان، همه منابع، ۱ کارگر. برای دیدن اینکه مسیر زنده است.",
        "limit": 5,
        "workers": 1,
        "loose": True,
        "skip_done": True,
        "pause": 0.5,
        "per_page": 6,
    },
    "woocommerce": {
        "label": "فقط ووکامرس",
        "blurb": "۹ فروشگاه با Store API. سریع‌تر و تمیزتر از صفحهٔ HTML.",
        "limit": 15,
        "workers": 1,
        "loose": True,
        "skip_done": True,
        "no_html": True,
        "no_market": True,
        "pause": 0.4,
        "per_page": 8,
    },
    "html": {
        "label": "فقط صفحهٔ فروشگاه",
        "blurb": "anik، allsport و ایران‌اسپورتر — جستجوی صفحه، بدون API محصول.",
        "limit": 8,
        "workers": 1,
        "loose": True,
        "skip_done": True,
        "shops": ["anik.ir", "allsport.ir", "iransporter.com"],
        "pause": 0.6,
        "per_page": 6,
    },
    "iransporter": {
        "label": "ایران اسپورتر",
        "blurb": "API محصول‌شان بسته است. از صفحهٔ جستجوی ویترین /search/1/… مثل مرورگر می‌خوانیم.",
        "limit": 8,
        "workers": 1,
        "loose": True,
        "skip_done": True,
        "shops": ["iransporter.com"],
        "pause": 0.7,
        "per_page": 8,
    },
    "market": {
        "label": "فقط بازار",
        "blurb": "دیجی‌کالا و باسلام. یک کوئری، چند فروشنده. کمی سنگین‌تر.",
        "limit": 6,
        "workers": 1,
        "loose": True,
        "skip_done": True,
        "shops": ["digikala.com", "basalam.com"],
        "pause": 0.6,
        "per_page": 6,
    },
    "strict": {
        "label": "سخت‌گیرانه",
        "blurb": "فقط ووکامرس، بدون «شبیه». فقط وقتی عکس و عنوان هر دو تأیید کنند.",
        "limit": 10,
        "workers": 1,
        "loose": False,
        "skip_done": True,
        "no_html": True,
        "no_market": True,
        "pause": 0.4,
        "per_page": 8,
    },
}

SOURCE_GROUPS = [
    {
        "kind": "woocommerce",
        "title": "فروشگاه ووکامرس",
        "blurb": "از /wp-json/wc/store/v1/products می‌خوانند. همان API ویترین خودشان است؛ لاگین نمی‌خواهد. کراولر نام کالای ما را جستجو می‌کند، عکس را هش می‌کند، بعد عنوان را چک می‌کند.",
        "items": [{"host": s.host, "name": s.name} for s in SHOPS],
    },
    {
        "kind": "html",
        "title": "صفحهٔ جستجو",
        "blurb": "API محصول ندارند یا بسته‌اند. کراولر صفحهٔ جستجوی ویترین را مثل مرورگر می‌خواند. ایران‌اسپورتر Store API ندارد؛ مسیرش /search/1/نام.aspx و کارت /product/…aspx است.",
        "items": [{"host": s.host, "name": s.name} for s in HTML_SHOPS],
    },
    {
        "kind": "market",
        "title": "بازار سراسری",
        "blurb": "یک جستجو چند فروشنده را می‌آورد. قیمت‌ها ریال است و به تومان تبدیل می‌شود. ترب به‌خاطر کپچا در این شبکه نیست.",
        "items": [
            {"host": "digikala.com", "name": "دیجی‌کالا"},
            {"host": "basalam.com", "name": "باسلام"},
        ],
    },
]

ALL_HOSTS = [item["host"] for g in SOURCE_GROUPS for item in g["items"]]
