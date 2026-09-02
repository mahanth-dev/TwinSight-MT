from django import template

register = template.Library()


@register.filter
def irt(value):
    if value in (None, ""):
        return "—"
    raw = str(value).strip()
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return raw
    return f"{n:,}"


@register.filter
def stock_fa(value):
    return {
        "instock": "موجود",
        "outofstock": "ناموجود",
        "onbackorder": "پیش‌سفارش",
    }.get(value or "", value or "—")


@register.filter
def type_fa(value):
    return {"simple": "ساده", "variable": "متغیر"}.get(value or "", value or "—")
