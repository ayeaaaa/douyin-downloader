import os
import shutil
import time
from pathlib import Path

import yt_dlp

from .security import is_safe_public_url


class DownloadError(Exception):
    pass


def download_to_temp(
    url: str,
    dest_dir: str,
    cookies_path: str | None = None,
    max_filesize_mb: int = 500,
) -> tuple[Path, str]:
    if not is_safe_public_url(url):
        raise DownloadError("不支持的链接")

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    max_bytes = max_filesize_mb * 1024 * 1024
    options = {
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "max_filesize": max_bytes,
    }
    if cookies_path and os.path.isfile(cookies_path):
        options["cookiefile"] = cookies_path

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(str(exc)) from exc

    title = (info or {}).get("title") or "video"
    files = [
        item
        for item in dest.iterdir()
        if item.is_file() and not item.name.endswith((".part", ".ytdl"))
    ]
    if not files:
        raise DownloadError("下载失败:未生成文件")
    path = max(files, key=lambda item: item.stat().st_size)
    if path.stat().st_size > max_bytes:
        path.unlink(missing_ok=True)
        raise DownloadError(f"视频超过 {max_filesize_mb} MB 限制")
    return path, title


def cleanup_file(path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_stale(dest_dir: str, max_age_seconds: int = 3600) -> None:
    root = Path(dest_dir)
    if not root.is_dir():
        return
    now = time.time()
    for item in root.iterdir():
        try:
            if now - item.stat().st_mtime <= max_age_seconds:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_file():
                item.unlink()
        except OSError:
            pass


def cleanup_dir(path) -> None:
    shutil.rmtree(path, ignore_errors=True)
