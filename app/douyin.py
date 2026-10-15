import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from .http_safe import BROWSER_UA, redirect_target
from .security import is_safe_public_url
from .signer_client import get_signer

DOUYIN_REFERER = "https://www.douyin.com/"
DOUYIN_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")
TTWID_REGISTER_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
TTWID_PAYLOAD = {
    "region": "cn",
    "aid": 1768,
    "needFid": False,
    "service": "douyin.com",
    "migrate_info": {"ticket": "", "source": "node"},
    "cbUrlProtocol": "https",
    "union": True,
}


def is_douyin_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(
        host == suffix or host.endswith("." + suffix) for suffix in DOUYIN_HOST_SUFFIXES
    )


def fetch_ttwid(timeout: float = 10.0) -> str | None:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(TTWID_REGISTER_URL, json=TTWID_PAYLOAD)
    except httpx.HTTPError:
        return None
    for header in response.headers.get_list("set-cookie"):
        if header.startswith("ttwid="):
            return header.split(";", 1)[0].split("=", 1)[1]
    return None


def ensure_cookies(cookies_path: str | None) -> str | None:
    if not cookies_path:
        return None
    path = Path(cookies_path)
    if path.is_file():
        return str(path)
    ttwid = fetch_ttwid()
    if not ttwid:
        return None
    expires = int(time.time()) + 31536000
    content = (
        "# Netscape HTTP Cookie File\n"
        f".douyin.com\tTRUE\t/\tFALSE\t{expires}\tttwid\t{ttwid}\n"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
    except OSError:
        return None
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as file:
            file.write(content)
        try:
            os.link(temp_name, path)
        except FileExistsError:
            return str(path)
    except OSError:
        return None
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
    return str(path)


def apply_douyin_options(options: dict, url: str, cookies_path: str | None) -> None:
    if not is_douyin_url(url):
        return
    cookie_file = ensure_cookies(cookies_path)
    if cookie_file:
        options["cookiefile"] = cookie_file
    options.setdefault("http_headers", {})["Referer"] = DOUYIN_REFERER


SLIDES_URL_RE = re.compile(r"/(?:share/slides|note)/(?P<id>\d+)")
VIDEO_URL_RE = re.compile(r"/(?:video|share/video)/(?P<id>\d+)")
DOUYIN_DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
DOUYIN_DETAIL_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
}
RISK_CONTROL_ERROR = (
    "抖音风控临时拦截(非登录问题):请 1-2 分钟后重试;"
    "持续失败请导出浏览器 cookies.txt 到 data/ 目录"
)


def load_cookie_dict(cookies_path: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not cookies_path or not os.path.isfile(cookies_path):
        return cookies
    try:
        with open(cookies_path, encoding="utf-8", errors="replace") as file:
            for line in file:
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_") :]
                elif line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7:
                    domain = parts[0].lstrip(".").lower()
                    if not (
                        domain == "douyin.com"
                        or domain.endswith(".douyin.com")
                        or domain == "iesdouyin.com"
                        or domain.endswith(".iesdouyin.com")
                    ):
                        continue
                    cookies[parts[5]] = parts[6]
    except OSError:
        return {}
    return cookies


SIGNED_FETCH_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.douyin.com",
    "Referer": "https://www.douyin.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def fetch_detail_signed(
    aweme_id: str,
    cookies: dict[str, str],
    params: dict[str, str],
    timeout: float = 20.0,
) -> dict | None:
    """Fetch the aweme detail through the Node signer + Firefox TLS.

    Returns the parsed payload on success, ``None`` when the signer or
    ``curl_cffi`` is unavailable or the request fails.
    """
    signer = get_signer()
    if not signer.available:
        return None
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    query = urlencode({"aweme_id": aweme_id, **params})
    signed = signer.sign(f"/aweme/v1/web/aweme/detail/?{query}", cookies)
    if not signed or not signed.get("signedUrl"):
        return None
    merged = dict(cookies)
    merged.update(signed.get("cookies") or {})
    try:
        response = curl_requests.get(
            signed["signedUrl"],
            headers=SIGNED_FETCH_HEADERS,
            cookies=merged,
            impersonate="firefox",
            timeout=timeout,
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def resolve_douyin_url(url: str, timeout: float = 10.0, max_redirects: int = 5) -> str:
    current = url
    try:
        with httpx.Client(timeout=timeout) as client:
            for _ in range(max_redirects + 1):
                if not is_safe_public_url(current):
                    return url
                with client.stream(
                    "GET",
                    current,
                    headers={"User-Agent": BROWSER_UA},
                    follow_redirects=False,
                ) as response:
                    target = redirect_target(response, current)
                    if target is None:
                        return current
                current = target
        return url
    except (httpx.HTTPError, httpx.InvalidURL):
        return url


def build_slides_items(detail: dict) -> list[dict]:
    items: list[dict] = []
    images = detail.get("images")
    if not isinstance(images, list):
        images = []
    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict):
            continue
        url_list = image.get("url_list")
        if not isinstance(url_list, list):
            url_list = []
        preview = url_list[0] if url_list else None
        if not preview:
            continue
        video = image.get("video")
        play_addr = video.get("play_addr") if isinstance(video, dict) else None
        clip_urls = play_addr.get("url_list") if isinstance(play_addr, dict) else None
        if not isinstance(clip_urls, list):
            clip_urls = []
        if clip_urls:
            items.append(
                {
                    "kind": "clip",
                    "index": index,
                    "preview_url": preview,
                    "download_url": clip_urls[0],
                }
            )
            continue
        download_list = image.get("download_url_list")
        if not isinstance(download_list, list):
            download_list = []
        items.append(
            {
                "kind": "image",
                "index": index,
                "preview_url": preview,
                "download_url": download_list[0] if download_list else preview,
            }
        )
    music = detail.get("music")
    play_url = music.get("play_url") if isinstance(music, dict) else None
    music_url = play_url.get("uri") if isinstance(play_url, dict) else None
    if music_url:
        items.append(
            {
                "kind": "music",
                "index": 1,
                "preview_url": music_url,
                "download_url": music_url,
            }
        )
    return items


def extract_video_signed(
    aweme_id: str, cookies_path: str | None, source_url: str
) -> dict | None:
    """Parse a Douyin video via the signed detail API.

    Returns a parse-result dict, or ``None`` when the signer is unavailable.
    """
    cookie_file = ensure_cookies(cookies_path)
    cookies = load_cookie_dict(cookie_file)
    payload = fetch_detail_signed(aweme_id, cookies, DOUYIN_DETAIL_PARAMS)
    if not isinstance(payload, dict):
        return None
    detail = payload.get("aweme_detail")
    if not isinstance(detail, dict):
        return None
    video = detail.get("video") if isinstance(detail.get("video"), dict) else {}
    play = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
    play_urls = play.get("url_list") if isinstance(play.get("url_list"), list) else []
    direct_url = next(
        (u for u in play_urls if isinstance(u, str) and u.startswith("http")), None
    )
    author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
    cover = video.get("cover") if isinstance(video.get("cover"), dict) else {}
    cover_urls = (
        cover.get("url_list") if isinstance(cover.get("url_list"), list) else []
    )
    duration = video.get("duration")
    return {
        "url": source_url,
        "media_type": "video",
        "ok": True,
        "title": detail.get("desc") or "",
        "author": author.get("nickname") or "",
        "cover": cover_urls[0] if cover_urls else "",
        "duration": int(duration // 1000) if isinstance(duration, (int, float)) else 0,
        "direct_url": direct_url,
        "direct_ok": False,
        "error": None,
    }


def extract_video_signed_from_url(url: str, cookies_path: str | None) -> dict | None:
    """Resolve the URL and parse the video through the signed detail API."""
    final_url = resolve_douyin_url(url)
    match = VIDEO_URL_RE.search(final_url) or VIDEO_URL_RE.search(url)
    if not match:
        return None
    return extract_video_signed(match.group("id"), cookies_path, url)


def extract_slides(aweme_id: str, cookies_path: str | None, source_url: str) -> dict:
    result = {
        "url": source_url,
        "ok": False,
        "media_type": "slides",
        "title": "",
        "author": "",
        "cover": "",
        "duration": 0,
        "direct_url": None,
        "direct_ok": False,
        "error": None,
        "items": [],
    }
    cookie_file = ensure_cookies(cookies_path)
    cookies = load_cookie_dict(cookie_file)
    params = {"aweme_id": aweme_id, **DOUYIN_DETAIL_PARAMS}
    headers = {"User-Agent": BROWSER_UA, "Referer": DOUYIN_REFERER}
    detail = None

    # Preferred path: Node signer (a_bogus + secsdk signatures) + Firefox TLS.
    payload = fetch_detail_signed(aweme_id, cookies, DOUYIN_DETAIL_PARAMS)
    if isinstance(payload, dict):
        detail = payload.get("aweme_detail")
        if not isinstance(detail, dict):
            detail = None

    if detail is None:
        try:
            with httpx.Client(timeout=20, cookies=cookies) as client:
                response = client.get(
                    DOUYIN_DETAIL_URL,
                    params=params,
                    headers=headers,
                )
        except httpx.HTTPError:
            result["error"] = "网络超时,请重试"
            return result
        if response.status_code == 200:
            try:
                payload = response.json() or {}
            except ValueError:
                payload = {}
            if isinstance(payload, dict):
                detail = payload.get("aweme_detail")
            if not isinstance(detail, dict):
                detail = None
    if not detail:
        result["error"] = RISK_CONTROL_ERROR
        return result
    items = build_slides_items(detail)
    if not items:
        result["error"] = "未找到可下载的图片或视频"
        return result
    result["ok"] = True
    result["title"] = detail.get("desc") or ""
    author = detail.get("author")
    result["author"] = (
        author.get("nickname") if isinstance(author, dict) else ""
    ) or ""
    result["cover"] = items[0].get("preview_url") or ""
    result["items"] = items
    return result
