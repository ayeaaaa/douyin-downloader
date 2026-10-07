import os
import re

import httpx
import yt_dlp

from . import douyin
from .http_safe import redirect_target
from .security import is_safe_public_url

URL_RE = re.compile(
    r"https?://[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\"'<>]+",
    re.IGNORECASE,
)
TRAILING_CHARS = ".,;:!?)]}>'\"，。！？、；：）】》」"


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(TRAILING_CHARS)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def humanize_error(exc: Exception, url: str | None = None) -> str:
    lowered = str(exc).lower()
    if "share/slides" in lowered or "is_slides" in lowered or "/note/" in lowered:
        return "这是图文/幻灯片帖子,暂不支持下载"
    if "login" in lowered or "cookie" in lowered or "sign in" in lowered:
        if url and douyin.is_douyin_url(url):
            return (
                "抖音风控临时拦截(非登录问题):请 1-2 分钟后重试;"
                "持续失败请导出浏览器 cookies.txt 到 data/ 目录"
            )
        return "需要登录,请配置 cookies.txt"
    if "unsupported url" in lowered:
        return "不支持的链接"
    if "not found" in lowered or "404" in lowered:
        return "视频不存在或已被删除"
    if "timed out" in lowered or "timeout" in lowered:
        return "网络超时,请重试"
    return "解析失败,请稍后重试"


def pick_direct_format(info: dict) -> tuple[str | None, dict]:
    formats = info.get("formats") or []
    progressive = [
        f
        for f in formats
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    if not progressive:
        return None, {}
    mp4 = [f for f in progressive if f.get("ext") == "mp4"]
    candidates = mp4 or progressive
    best = max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    headers = dict(best.get("http_headers") or {})
    return best["url"], headers


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def probe_direct(url: str, headers: dict, timeout: float = 10.0) -> bool:
    request_headers = {"User-Agent": BROWSER_UA}
    request_headers.update({k: v for k, v in headers.items() if k.lower() != "referer"})
    current = url
    try:
        with httpx.Client(timeout=timeout) as client:
            for _ in range(6):
                if not is_safe_public_url(current):
                    return False
                with client.stream(
                    "GET",
                    current,
                    headers={**request_headers, "Range": "bytes=0-0"},
                    follow_redirects=False,
                ) as response:
                    target = redirect_target(response, current)
                    if target is None:
                        return response.status_code in (200, 206)
                current = target
        return False
    except (httpx.HTTPError, httpx.InvalidURL):
        return False


def parse_url(url: str, cookies_path: str | None = None, probe: bool = True) -> dict:
    result = {
        "url": url,
        "ok": False,
        "title": "",
        "author": "",
        "cover": "",
        "duration": 0,
        "direct_url": None,
        "direct_ok": False,
        "error": None,
    }
    if not is_safe_public_url(url):
        result["error"] = "不支持的链接"
        return result

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }
    if cookies_path and os.path.isfile(cookies_path):
        options["cookiefile"] = cookies_path
    douyin.apply_douyin_options(options, url, cookies_path)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        result["error"] = humanize_error(exc, url)
        return result

    if info.get("_type") == "playlist":
        entries = [entry for entry in info.get("entries") or [] if entry]
        info = entries[0] if entries else info

    result["ok"] = True
    result["title"] = info.get("title") or ""
    result["author"] = info.get("uploader") or info.get("creator") or ""
    result["cover"] = info.get("thumbnail") or ""
    result["duration"] = int(info.get("duration") or 0)

    direct_url, headers = pick_direct_format(info)
    if direct_url:
        result["direct_url"] = direct_url
        result["direct_ok"] = probe_direct(direct_url, headers) if probe else True
    return result
