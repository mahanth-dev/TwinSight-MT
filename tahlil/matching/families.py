"""Product family detection — used to block false matches (e.g. mat vs t-shirt)."""

from __future__ import annotations

import re

# Distinctive type buckets. A product may match one family.
# Order matters: more specific patterns first.
FAMILY_PATTERNS: list[tuple[str, str, list[str]]] = [
    ("yoga", "یوگا / مت", ["یوگا", "آجر یوگا", "مت یوگا", "زيرانداز", "زیرانداز", "زیر‌انداز", "yoga"]),
    ("dart", "دارت", ["دارت", "dart", "mission spirit", "فلش دارت", "تخته دارت"]),
    ("table-tennis", "پینگ‌پنگ", ["پینگ پنگ", "پینگ‌پنگ", "پينگ پنگ", "table tennis", "ping pong"]),
    ("racket", "راکت", ["راکت", "بدمینتون", "بدمينتون", "تنیس", "تنیس روی میز", "yonex", "یونکس", "کاور راکت"]),
    ("ball", "توپ", ["توپ فوتبال", "توپ والیبال", "توپ بسکتبال", "توپ هندبال", "توپ ", "football", "select numero"]),
    ("swim", "شنا", ["عینک شنا", "کلاه شنا", "مایو", "شنا ", "اسپیدو", "speedo", "arena", "آرنا", "شنای"]),
    ("bottle", "قمقمه / شیکر", ["قمقمه", "شیکر", "بوتل", "bottle", "shaker"]),
    ("glove", "دستکش", ["دستکش", "gloves", "گلوز"]),
    ("shoe", "کفش", ["کفش", "کتانی", "اسنیکر", "sneakers", "جامپ شو", "کفش فوتبال", "استوک"]),
    ("bag", "کیف / کوله", ["کوله", "کیف ورزشی", "ساک ورزشی", "backpack", "دافل"]),
    ("sock", "جوراب", ["جوراب", "socks"]),
    ("cap", "کلاه", ["کلاه ", "هدبند", "سرپوش", "visors"]),
    ("apparel-set", "ست لباس", ["ست پیراهن", "ست گرمکن", "ست ورزشی", "شورت و پیراهن"]),
    ("apparel", "پوشاک", [
        "تیشرت", "تی‌شرت", "تيشرت", "تاپ ", "هودی", "سویشرت", "سوئیشرت",
        "شورت", "لگ ", "لگینگ", "گرمکن", "پیراهن", "شلوار", "استرچ",
        "آستین", "حلقه‌ای", "هالتری", "filaments", "فیلامنت",
    ]),
    ("fitness", "تناسب اندام", [
        "دمبل", "طناب", "کش ", "تردمیل", "بارفیکس", "فنر تقویت",
        "مچ ", "بدنسازی", "وزنه‌", "کettle", "گارد",
    ]),
    ("accessory", "اکسسوری", ["عینک", "مچبند", "چسب", "بند ", "کاور ", "واکس", "سوت"]),
]

STOPWORDS = {
    "ست", "مدل", "رنگ", "سایز", "سايز", "مردانه", "زنانه", "بچگانه", "کودک",
    "ورزشی", "ورزشي", "اصل", "خرید", "فروش", "برند", "جدید", "حرفه‌ای",
    "حرفه ای", "حرفه", "با", "برای", "از", "و", "در", "تا", "این", "آن",
    "the", "and", "for", "with", "size", "color", "mm", "میل", "عدد",
    "جفت", "ارسال", "رایگان", "آساره", "اسپرت", "asareh",
}


def normalize(text: str) -> str:
    text = (text or "").casefold()
    text = text.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    text = re.sub(r"[^\w\s+-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _family_blob(text: str) -> str:
    """Like normalize, but ZWNJ is removed rather than widened into a space,
    so a compound such as «کفش‌دوزک» never reads as the word «کفش»."""
    text = (text or "").casefold().replace("ي", "ی").replace("ك", "ک")
    text = text.replace("\u200c", "")
    text = re.sub(r"[^\w\s+-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def detect_family(name: str, cats: str = "") -> tuple[str, str]:
    blob = _family_blob(f"{name} {cats}")
    for fid, label, keys in FAMILY_PATTERNS:
        for key in keys:
            k = _family_blob(key)
            if k and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", blob):
                return fid, label
    return "other", "سایر"


def title_tokens(text: str) -> set[str]:
    parts = normalize(text).split()
    out = set()
    for p in parts:
        if p in STOPWORDS:
            continue
        if len(p) < 2:
            continue
        out.add(p)
        # keep latin brand-like tokens even if short (ALA)
        if re.fullmatch(r"[a-zA-Z]{2,}", p):
            out.add(p.lower())
    return out


def title_score(a: str, b: str) -> float:
    """Jaccard on distinctive tokens. 0 if either side is empty of tokens."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        # partial prefix match for persian stems (مت / مت‌ها)
        extra = 0
        for x in ta:
            for y in tb:
                if len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x)):
                    extra += 1
                    break
        inter = extra
    union = len(ta | tb)
    return inter / union if union else 0.0


# Latin words that say nothing about which model this is.
LATIN_NOISE = {
    "pro", "sport", "sports", "model", "new", "original", "official", "size",
    "color", "made", "china", "free", "shipping", "kg", "cm", "mm", "ml", "gr",
    "gram", "xs", "xl", "xxl", "xxxl", "set", "pack", "plus", "mini", "fitness",
    "gym", "men", "mens", "women", "womens", "kids", "unisex", "black", "white",
    "red", "blue", "green", "gray", "grey", "navy", "pink", "code", "type",
    "quality", "premium", "super", "best", "top", "line",
}
FA_TO_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def spec_codes(text: str) -> tuple[set[str], set[str]]:
    """Brand/model words and the numbers printed in a title.

    These carry the identity of a listing: ASTROX 88D is not ASTROX 77, and a
    1-litre bottle is not a 900ml bottle, however alike the two photos look.
    """
    blob = normalize((text or "").translate(FA_TO_EN_DIGITS))
    latin = {
        tok.strip("-")
        for tok in re.findall(r"[a-z][a-z0-9\-]{1,}", blob)
        if tok not in LATIN_NOISE and len(tok.strip("-")) >= 2
    }
    numbers = {n.lstrip("0") or "0" for n in re.findall(r"\d+", blob)}
    return latin - LATIN_NOISE, numbers


def spec_relation(a: str, b: str) -> str:
    """How the two titles agree on model identity: "clash", "thin" or "ok".

    "thin" means one side prints a model number and the other prints none, so
    there is nothing to confirm they are the same variant.
    """
    latin_a, num_a = spec_codes(a)
    latin_b, num_b = spec_codes(b)
    if latin_a and latin_b and not (latin_a & latin_b):
        return "clash"
    if num_a and num_b and not (num_a & num_b):
        return "clash"
    if bool(num_a) != bool(num_b):
        return "thin"
    return "ok"


def specs_conflict(a: str, b: str) -> bool:
    return spec_relation(a, b) == "clash"


def families_conflict(fa: str, fb: str) -> bool:
    if fa == "other" or fb == "other":
        return False
    if fa == fb:
        return False
    # apparel-set vs apparel is compatible
    apparel = {"apparel", "apparel-set", "sock", "cap"}
    if fa in apparel and fb in apparel:
        return False
    return True
