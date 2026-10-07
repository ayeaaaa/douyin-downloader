import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .http_safe import BROWSER_UA, redirect_target
from .security import is_safe_public_url

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
                    cookies[parts[5]] = parts[6]
    except OSError:
        return {}
    return cookies


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
    for index, image in enumerate(detail.get("images") or [], start=1):
        url_list = image.get("url_list") or []
        preview = url_list[0] if url_list else None
        if not preview:
            continue
        clip_urls = ((image.get("video") or {}).get("play_addr") or {}).get(
            "url_list"
        ) or []
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
        download_list = image.get("download_url_list") or []
        items.append(
            {
                "kind": "image",
                "index": index,
                "preview_url": preview,
                "download_url": download_list[0] if download_list else preview,
            }
        )
    music_url = ((detail.get("music") or {}).get("play_url") or {}).get("uri")
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
    detail = None
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
    result["author"] = (detail.get("author") or {}).get("nickname") or ""
    result["cover"] = items[0].get("preview_url") or ""
    result["items"] = items
    return result
