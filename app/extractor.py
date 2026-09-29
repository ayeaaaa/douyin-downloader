import re

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


def humanize_error(exc: Exception) -> str:
    lowered = str(exc).lower()
    if "login" in lowered or "cookie" in lowered or "sign in" in lowered:
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
