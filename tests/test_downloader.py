from pathlib import Path

import httpx
import pytest

from app import downloader


def test_download_to_temp_returns_file_and_title(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            assert download is True
            Path(self.opts["outtmpl"]).parent.joinpath("123.mp4").write_bytes(b"data")
            return {"title": "标题"}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(downloader, "is_safe_public_url", lambda url: True)

    path, title = downloader.download_to_temp("https://v.douyin.com/a/", str(tmp_path))

    assert title == "标题"
    assert path.read_bytes() == b"data"


def test_download_to_temp_rejects_private_url(tmp_path):
    with pytest.raises(downloader.DownloadError):
        downloader.download_to_temp("http://127.0.0.1/x", str(tmp_path))


def test_download_to_temp_enforces_max_size(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            Path(self.opts["outtmpl"]).parent.joinpath("big.mp4").write_bytes(
                b"x" * 2048
            )
            return {"title": "big"}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(downloader, "is_safe_public_url", lambda url: True)

    with pytest.raises(downloader.DownloadError):
        downloader.download_to_temp(
            "https://v.douyin.com/a/", str(tmp_path), max_filesize_mb=0
        )
    assert not (tmp_path / "big.mp4").exists()


def test_download_to_temp_douyin_sets_referer_and_cookies(tmp_path, monkeypatch):
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured.update(opts)
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            Path(self.opts["outtmpl"]).parent.joinpath("1.mp4").write_bytes(b"x")
            return {"title": "t"}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(downloader, "is_safe_public_url", lambda url: True)
    monkeypatch.setattr(downloader.douyin, "fetch_ttwid", lambda: "tok123")
    cookies_path = str(tmp_path / "cookies.txt")

    downloader.download_to_temp("https://v.douyin.com/x/", str(tmp_path), cookies_path)

    assert captured["http_headers"] == {"Referer": downloader.douyin.DOUYIN_REFERER}
    assert captured["cookiefile"] == cookies_path


def test_fetch_direct_to_temp_writes_file(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"data")

    real_client = httpx.Client
    monkeypatch.setattr(
        downloader.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(downloader, "is_safe_public_url", lambda url: True)

    path = downloader.fetch_direct_to_temp(
        "https://cdn.example.com/v.mp4", str(tmp_path / "v.mp4"), 500
    )
    assert path.read_bytes() == b"data"


def test_fetch_direct_to_temp_rejects_unsafe_url(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "is_safe_public_url", lambda url: False)
    with pytest.raises(downloader.DownloadError):
        downloader.fetch_direct_to_temp(
            "http://127.0.0.1/x", str(tmp_path / "v.mp4"), 500
        )


def test_fetch_direct_to_temp_enforces_max_size(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"x" * 2048)

    real_client = httpx.Client
    monkeypatch.setattr(
        downloader.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(downloader, "is_safe_public_url", lambda url: True)
    dest = tmp_path / "v.mp4"
    with pytest.raises(downloader.DownloadError):
        downloader.fetch_direct_to_temp("https://cdn.example.com/v.mp4", str(dest), 0)
    assert not dest.exists()


def test_cleanup_stale_removes_old_files(tmp_path):
    old = tmp_path / "old.mp4"
    old.write_bytes(b"x")
    downloader.cleanup_stale(str(tmp_path), max_age_seconds=0)
    assert not old.exists()


def test_cleanup_stale_removes_old_dirs(tmp_path):
    old_dir = tmp_path / "job-old"
    old_dir.mkdir()
    (old_dir / "video.mp4").write_bytes(b"x")
    downloader.cleanup_stale(str(tmp_path), max_age_seconds=0)
    assert not old_dir.exists()
