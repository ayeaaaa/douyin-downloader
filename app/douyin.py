import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

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
        temp_path = path.with_name(path.name + ".tmp")
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    except OSError:
        return None
    return str(path)


def apply_douyin_options(options: dict, url: str, cookies_path: str | None) -> None:
    if not is_douyin_url(url):
        return
    cookie_file = ensure_cookies(cookies_path)
    if cookie_file:
        options["cookiefile"] = cookie_file
    options["http_headers"] = {"Referer": DOUYIN_REFERER}
