import base64
import ipaddress
import re
import secrets
import socket
import threading
import time
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

ALLOWED_COVER_SUFFIXES = (
    "douyin.com",
    "iesdouyin.com",
    "douyinpic.com",
    "douyinvod.com",
    "byteimg.com",
    "ibytedtos.com",
    "bytecdntp.com",
    "zjcdn.com",
    "snssdk.com",
)

_FILENAME_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_FILENAME_EDGE = re.compile(r"^[.\s]+|[.\s]+$")


def sanitize_filename(name: str, max_length: int = 120) -> str:
    name = _FILENAME_BAD_CHARS.sub("_", name or "")
    name = _FILENAME_EDGE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "video"


def _is_public_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


_DNS_CACHE_TTL = 30.0
_DNS_CACHE_MAX = 512
_dns_cache: dict[str, tuple[float, bool]] = {}
_dns_lock = threading.Lock()


def _host_is_public(host: str, port: int) -> bool:
    now = time.monotonic()
    with _dns_lock:
        cached = _dns_cache.get(host)
        if cached and cached[0] > now:
            return cached[1]
    try:
        infos = socket.getaddrinfo(host, port)
    except (OSError, ValueError):
        return False
    result = all(_is_public_ip(info[4][0]) for info in infos)
    with _dns_lock:
        if len(_dns_cache) >= _DNS_CACHE_MAX:
            _dns_cache.clear()
        _dns_cache[host] = (now + _DNS_CACHE_TTL, result)
    return result


def is_safe_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    return _host_is_public(parsed.hostname, port)


def is_allowed_cover_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    allowed = any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ALLOWED_COVER_SUFFIXES
    )
    return allowed and is_safe_public_url(url)


ALLOWED_MEDIA_SUFFIXES = (
    "douyin.com",
    "iesdouyin.com",
    "douyinpic.com",
    "douyinvod.com",
    "douyinstatic.com",
    "byteimg.com",
    "ibytedtos.com",
    "bytecdntp.com",
    "zjcdn.com",
    "snssdk.com",
    "amemv.com",
    "365yg.com",
)


def is_allowed_media_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    allowed = any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ALLOWED_MEDIA_SUFFIXES
    )
    return allowed and is_safe_public_url(url)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, password: str):
        super().__init__(app)
        self.password = password

    async def dispatch(self, request, call_next):
        if not self.password or request.url.path == "/healthz":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                _, _, password = decoded.partition(":")
                if secrets.compare_digest(
                    password.encode("utf-8"), self.password.encode("utf-8")
                ):
                    return await call_next(request)
            except Exception:
                pass
        return Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="douyin-dl"'},
        )
