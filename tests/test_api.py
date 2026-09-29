import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import downloader, extractor
from app.main import Settings, create_app, _stream_file


def make_client(tmp_path, **overrides):
    settings = Settings(
        access_password=overrides.get("access_password", ""),
        max_filesize_mb=overrides.get("max_filesize_mb", 500),
        cookies_path=str(tmp_path / "cookies.txt"),
        temp_dir=str(tmp_path),
    )
    return TestClient(create_app(settings))


def test_healthz(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/healthz").json() == {"status": "ok"}


def test_parse_requires_link(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/parse", json={"text": "没有链接"})
    assert response.status_code == 400


def test_parse_rejects_too_many_links(tmp_path):
    text = " ".join(f"https://v.douyin.com/x{i}/" for i in range(21))
    client = make_client(tmp_path)
    response = client.post("/api/parse", json={"text": text})
    assert response.status_code == 400


def test_parse_rejects_too_long_text(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/parse", json={"text": "a" * 20001})
    assert response.status_code == 400


def test_parse_returns_results(tmp_path, monkeypatch):
    def fake_parse(url, cookies_path=None):
        return {
            "url": url,
            "ok": True,
            "title": "t",
            "author": "",
            "cover": "",
            "duration": 0,
            "direct_url": None,
            "direct_ok": False,
            "error": None,
        }

    monkeypatch.setattr(extractor, "parse_url", fake_parse)
    client = make_client(tmp_path)
    response = client.post("/api/parse", json={"text": "https://v.douyin.com/a/"})
    assert response.status_code == 200
    assert response.json()["results"][0]["url"] == "https://v.douyin.com/a/"


def test_download_streams_and_cleans_up(tmp_path, monkeypatch):
    def fake_download(url, dest_dir, cookies_path=None, max_filesize_mb=500):
        path = Path(dest_dir) / "video.mp4"
        path.write_bytes(b"video-bytes")
        return path, "测试视频"

    monkeypatch.setattr(downloader, "download_to_temp", fake_download)
    client = make_client(tmp_path)
    response = client.get("/api/download", params={"url": "https://v.douyin.com/a/"})
    assert response.status_code == 200
    assert response.content == b"video-bytes"
    assert "filename*=utf-8''" in response.headers["content-disposition"]
    assert list(tmp_path.rglob("*.mp4")) == []


def test_download_failure_cleans_job_dir(tmp_path, monkeypatch):
    def fake_download(url, dest_dir, cookies_path=None, max_filesize_mb=500):
        (Path(dest_dir) / "partial.part").write_bytes(b"x")
        raise downloader.DownloadError("boom")

    monkeypatch.setattr(downloader, "download_to_temp", fake_download)
    client = make_client(tmp_path)
    response = client.get("/api/download", params={"url": "https://v.douyin.com/a/"})
    assert response.status_code == 502
    assert list(tmp_path.iterdir()) == []


def test_cover_rejects_unknown_domain(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/cover", params={"url": "https://evil.com/a.jpg"})
    assert response.status_code == 400


def test_auth_enabled(tmp_path):
    client = make_client(tmp_path, access_password="secret")
    params = {"url": "https://evil.com/a.jpg"}
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/cover", params=params).status_code == 401
    assert (
        client.get("/api/cover", params=params, auth=("u", "secret")).status_code == 400
    )


def test_download_returns_429_when_busy(tmp_path):
    client = make_client(tmp_path)
    semaphore = client.app.state.download_semaphore

    async def run():
        await semaphore.acquire()
        try:
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as http:
                return await http.get(
                    "/api/download", params={"url": "https://v.douyin.com/a/"}
                )
        finally:
            semaphore.release()

    response = asyncio.run(run())
    assert response.status_code == 429


def test_stream_file_releases_and_cleans(tmp_path):
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    path = job_dir / "video.mp4"
    path.write_bytes(b"data")
    semaphore = asyncio.Semaphore(1)

    async def run():
        await semaphore.acquire()
        chunks = []
        async for chunk in _stream_file(path, str(job_dir), semaphore):
            chunks.append(chunk)
        return chunks, semaphore.locked()

    chunks, locked = asyncio.run(run())
    assert b"".join(chunks) == b"data"
    assert not job_dir.exists()
    assert locked is False


def test_stream_file_early_close_releases(tmp_path):
    job_dir = tmp_path / "job-2"
    job_dir.mkdir()
    path = job_dir / "video.mp4"
    path.write_bytes(b"data")
    semaphore = asyncio.Semaphore(1)

    async def run():
        await semaphore.acquire()
        generator = _stream_file(path, str(job_dir), semaphore)
        first = await generator.__anext__()
        await generator.aclose()
        return first, semaphore.locked()

    first, locked = asyncio.run(run())
    assert first == b"data"
    assert not job_dir.exists()
    assert locked is False
