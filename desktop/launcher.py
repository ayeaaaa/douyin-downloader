"""Douyin Downloader desktop launcher.

Starts the local web server and opens the browser. Works both from source
(``python desktop/launcher.py``) and from the PyInstaller bundle.
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path


def _app_dir() -> Path:
    """Directory that holds user data (cookies, downloads), next to the exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_dir() -> Path:
    """Read-only resources: PyInstaller temp dir when frozen, repo root otherwise."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


def main() -> None:
    port = int(os.environ.get("PORT", "8899"))

    data_dir = _app_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COOKIES_PATH", str(data_dir / "cookies.txt"))

    # Let the app package be importable from the bundle or the repo.
    resource_root = _resource_dir()
    if str(resource_root) not in sys.path:
        sys.path.insert(0, str(resource_root))

    import uvicorn
    from app.main import create_app

    url = f"http://127.0.0.1:{port}/"
    print("=" * 56)
    print("  抖音下载站 (本地版)")
    print(f"  访问地址: {url}")
    print("  保持本窗口打开;关闭窗口即退出程序")
    print("=" * 56)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
