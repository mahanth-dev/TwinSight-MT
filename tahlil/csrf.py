"""CSRF origin check that still works behind IP, port, or TLS proxy."""

from urllib.parse import urlparse

from django.middleware.csrf import CsrfViewMiddleware as DjangoCsrfViewMiddleware


def _hostname(value: str) -> str:
    if not value:
        return ""
    if value.startswith("["):
        return value.split("]")[0].lstrip("[").lower()
    return value.split(":")[0].lower()


class CsrfViewMiddleware(DjangoCsrfViewMiddleware):
    def _origin_verified(self, request):
        if super()._origin_verified(request):
            return True
        origin = request.META.get("HTTP_ORIGIN")
        if not origin or origin == "null":
            return False
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        try:
            request_host = request.get_host()
        except Exception:
            return False
        return parsed.hostname.lower() == _hostname(request_host)
