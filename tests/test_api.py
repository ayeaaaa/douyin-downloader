import asyncio
import io
import socket
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import downloader, extractor, main
from app.main import Settings, create_app, _RelayResponse


def make_client(tmp_path, **overrides):
    settings = Settings(
        access_password=overrides.get("access_password", ""),
        max_filesize_mb=overrides.get("max_filesize_mb", 500),
        cookies_path=str(tmp_path / "cookies.txt"),
        temp_dir=str(tmp_path),
        cache_ttl_seconds=overrides.get("cache_ttl_seconds", 900),
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


def test_relay_response_cleans_after_full_stream(tmp_path):
    job_dir = tmp_path / "job-full"
    job_dir.mkdir()
    path = job_dir / "video.mp4"
    path.write_bytes(b"data")
    semaphore = asyncio.Semaphore(1)
    response = _RelayResponse(
        path, str(job_dir), semaphore, media_type="video/mp4", headers={}
    )

    async def run():
        await semaphore.acquire()
        messages = []

        async def receive():
            await asyncio.sleep(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        await response(scope, receive, send)
        return messages, semaphore.locked()

    messages, locked = asyncio.run(run())
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    assert body == b"data"
    assert not job_dir.exists()
    assert locked is False


def test_relay_response_releases_on_immediate_disconnect(tmp_path):
    job_dir = tmp_path / "job-disc"
    job_dir.mkdir()
    path = job_dir / "video.mp4"
    path.write_bytes(b"data")
    semaphore = asyncio.Semaphore(1)
    response = _RelayResponse(
        path, str(job_dir), semaphore, media_type="video/mp4", headers={}
    )

    async def run():
        await semaphore.acquire()

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        await response(scope, receive, send)
        return semaphore.locked()

    locked = asyncio.run(run())
    assert not job_dir.exists()
    assert locked is False


def test_parse_rejects_too_large_body(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/parse", json={"text": "a" * 70000})
    assert response.status_code == 413


def test_parse_uses_cache(tmp_path, monkeypatch):
    calls = {"count": 0}

    def fake_parse(url, cookies_path=None):
        calls["count"] += 1
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
    body = {"text": "https://v.douyin.com/a/"}
    assert client.post("/api/parse", json=body).status_code == 200
    assert client.post("/api/parse", json=body).status_code == 200
    assert calls["count"] == 1


def test_parse_cache_ttl_zero_always_reparses(tmp_path, monkeypatch):
    calls = {"count": 0}

    def fake_parse(url, cookies_path=None):
        calls["count"] += 1
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
    client = make_client(tmp_path, cache_ttl_seconds=0)
    body = {"text": "https://v.douyin.com/a/"}
    client.post("/api/parse", json=body)
    client.post("/api/parse", json=body)
    assert calls["count"] == 2


def test_download_prefers_cached_direct_url(tmp_path, monkeypatch):
    calls = {"direct": 0, "ytdlp": 0}

    def fake_parse(url, cookies_path=None):
        return {
            "url": url,
            "ok": True,
            "title": "标题",
            "author": "",
            "cover": "",
            "duration": 0,
            "direct_url": "https://cdn.example.com/v.mp4",
            "direct_ok": True,
            "error": None,
        }

    def fake_fetch(direct_url, dest_path, max_filesize_mb=500, headers=None):
        calls["direct"] += 1
        path = Path(dest_path)
        path.write_bytes(b"direct-bytes")
        return path

    def fake_download(url, dest_dir, cookies_path=None, max_filesize_mb=500):
        calls["ytdlp"] += 1
        path = Path(dest_dir) / "video.mp4"
        path.write_bytes(b"ytdlp-bytes")
        return path, "标题"

    monkeypatch.setattr(extractor, "parse_url", fake_parse)
    monkeypatch.setattr(downloader, "fetch_direct_to_temp", fake_fetch)
    monkeypatch.setattr(downloader, "download_to_temp", fake_download)

    client = make_client(tmp_path)
    client.post("/api/parse", json={"text": "https://v.douyin.com/a/"})
    response = client.get("/api/download", params={"url": "https://v.douyin.com/a/"})
    assert response.status_code == 200
    assert response.content == b"direct-bytes"
    assert calls == {"direct": 1, "ytdlp": 0}


def test_download_falls_back_when_direct_fails(tmp_path, monkeypatch):
    calls = {"direct": 0, "ytdlp": 0}

    def fake_parse(url, cookies_path=None):
        return {
            "url": url,
            "ok": True,
            "title": "标题",
            "author": "",
            "cover": "",
            "duration": 0,
            "direct_url": "https://cdn.example.com/v.mp4",
            "direct_ok": True,
            "error": None,
        }

    def fake_fetch(direct_url, dest_path, max_filesize_mb=500, headers=None):
        calls["direct"] += 1
        raise downloader.DownloadError("boom")

    def fake_download(url, dest_dir, cookies_path=None, max_filesize_mb=500):
        calls["ytdlp"] += 1
        path = Path(dest_dir) / "video.mp4"
        path.write_bytes(b"ytdlp-bytes")
        return path, "标题"

    monkeypatch.setattr(extractor, "parse_url", fake_parse)
    monkeypatch.setattr(downloader, "fetch_direct_to_temp", fake_fetch)
    monkeypatch.setattr(downloader, "download_to_temp", fake_download)

    client = make_client(tmp_path)
    client.post("/api/parse", json={"text": "https://v.douyin.com/a/"})
    response = client.get("/api/download", params={"url": "https://v.douyin.com/a/"})
    assert response.status_code == 200
    assert response.content == b"ytdlp-bytes"
    assert calls == {"direct": 1, "ytdlp": 1}


def test_parse_handles_concurrent_requests(tmp_path, monkeypatch):
    import time

    def fake_parse(url, cookies_path=None):
        time.sleep(0.05)
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

    async def run():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as http:
            return await asyncio.gather(
                http.post("/api/parse", json={"text": "https://v.douyin.com/a/"}),
                http.post("/api/parse", json={"text": "https://v.douyin.com/b/"}),
            )

    responses = asyncio.run(run())
    assert [response.status_code for response in responses] == [200, 200]


def test_cookies_status_unconfigured(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/cookies/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_cookies_save_and_clear(tmp_path):
    client = make_client(tmp_path)
    content = (
        "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc\n"
    )
    response = client.post("/api/cookies", json={"content": content})
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["entries"] == 1
    assert isinstance(data["updated_at"], int)
    assert (tmp_path / "cookies.txt").is_file()

    response = client.delete("/api/cookies")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert not (tmp_path / "cookies.txt").exists()


def test_cookies_save_rejects_bad_format(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/cookies", json={"content": "hello"})
    assert response.status_code == 400


def test_cookies_save_rejects_content_over_limit(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/cookies", json={"content": "x" * (1024 * 1024 + 8192)})
    assert response.status_code == 400


def test_cookies_save_rejects_oversized_body(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/cookies", json={"content": "x" * (3 * 1024 * 1024)})
    assert response.status_code == 413


def test_cookies_save_accepts_near_limit_file(tmp_path):
    client = make_client(tmp_path)
    line = ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\t" + "x" * 60 + "\n"
    header = "# Netscape HTTP Cookie File\n"
    count = (1024 * 1024 - 1024) // len(line)
    content = header + line * count
    assert len(content.encode("utf-8")) < 1024 * 1024
    response = client.post("/api/cookies", json={"content": content})
    assert response.status_code == 200
    assert response.json()["entries"] == count


def test_cookies_save_rejects_non_string_content(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/cookies", json={"content": 123})
    assert response.status_code == 400


def test_cookies_save_clears_parse_cache(tmp_path, monkeypatch):
    calls = {"count": 0}

    def fake_parse(url, cookies_path=None):
        calls["count"] += 1
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
    body = {"text": "https://v.douyin.com/a/"}
    client.post("/api/parse", json=body)
    content = (
        "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc\n"
    )
    client.post("/api/cookies", json={"content": content})
    client.post("/api/parse", json=body)
    assert calls["count"] == 2


def test_cookies_status_requires_auth(tmp_path):
    client = make_client(tmp_path, access_password="secret")
    assert client.get("/api/cookies/status").status_code == 401
    assert client.get("/api/cookies/status", auth=("u", "secret")).status_code == 200


def test_media_rejects_unknown_domain(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/media", params={"url": "https://evil.com/a.mp4"})
    assert response.status_code == 400


def test_media_streams_content(tmp_path, monkeypatch):
    async def fake_open(client, url, headers=None, max_redirects=5, validator=None):
        return httpx.Response(
            200, content=b"media-bytes", headers={"content-type": "video/mp4"}
        )

    monkeypatch.setattr(main, "open_safe_stream", fake_open)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    client = make_client(tmp_path)
    response = client.get(
        "/api/media", params={"url": "https://v26-web.douyinvod.com/a.mp4"}
    )
    assert response.status_code == 200
    assert response.content == b"media-bytes"
    assert response.headers["content-type"] == "video/mp4"


def test_media_download_sets_attachment(tmp_path, monkeypatch):
    async def fake_open(client, url, headers=None, max_redirects=5, validator=None):
        return httpx.Response(
            200, content=b"data", headers={"content-type": "image/webp"}
        )

    monkeypatch.setattr(main, "open_safe_stream", fake_open)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    client = make_client(tmp_path)
    response = client.get(
        "/api/media",
        params={
            "url": "https://p3-sign.douyinpic.com/a.webp",
            "download": 1,
            "name": "图片.webp",
        },
    )
    assert response.status_code == 200
    assert "filename*=utf-8''" in response.headers["content-disposition"]


def test_media_rejects_unsafe_stream(tmp_path, monkeypatch):
    async def fake_open(client, url, headers=None, max_redirects=5, validator=None):
        return None

    monkeypatch.setattr(main, "open_safe_stream", fake_open)
    client = make_client(tmp_path)
    response = client.get(
        "/api/media", params={"url": "https://v26-web.douyinvod.com/a.mp4"}
    )
    assert response.status_code == 400


def test_slides_zip_packages_selected_items(tmp_path, monkeypatch):
    def fake_fetch(url, dest_path, max_filesize_mb=500, headers=None, validator=None):
        path = Path(dest_path)
        path.write_bytes(b"data-" + url.encode("utf-8"))
        return path

    monkeypatch.setattr(downloader, "fetch_direct_to_temp", fake_fetch)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    client = make_client(tmp_path)
    response = client.post(
        "/api/slides/zip",
        json={
            "title": "标题",
            "items": [
                {
                    "url": "https://p3-sign.douyinpic.com/a.webp",
                    "kind": "image",
                    "index": 1,
                },
                {
                    "url": "https://v26-web.douyinvod.com/b",
                    "kind": "clip",
                    "index": 2,
                },
            ],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ["clip-02.mp4", "image-01.webp"]


def test_slides_zip_rejects_unsafe_url(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/slides/zip",
        json={"items": [{"url": "https://evil.com/a", "kind": "image", "index": 1}]},
    )
    assert response.status_code == 400


def test_slides_zip_rejects_too_many_items(tmp_path):
    client = make_client(tmp_path)
    items = [
        {
            "url": "https://p3-sign.douyinpic.com/a.webp",
            "kind": "image",
            "index": index,
        }
        for index in range(1, 52)
    ]
    response = client.post("/api/slides/zip", json={"items": items})
    assert response.status_code == 400


def test_slides_zip_rejects_empty_items(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/slides/zip", json={"items": []})
    assert response.status_code == 400


def test_slides_zip_rejects_bad_index(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/slides/zip",
        json={
            "items": [
                {
                    "url": "https://p3-sign.douyinpic.com/a.webp",
                    "kind": "image",
                    "index": "abc",
                }
            ]
        },
    )
    assert response.status_code == 400


def test_media_rejects_non_media_content_type(tmp_path, monkeypatch):
    async def fake_open(client, url, headers=None, max_redirects=5, validator=None):
        return httpx.Response(
            200, content=b"<html></html>", headers={"content-type": "text/html"}
        )

    monkeypatch.setattr(main, "open_safe_stream", fake_open)
    client = make_client(tmp_path)
    response = client.get(
        "/api/media", params={"url": "https://v26-web.douyinvod.com/a.mp4"}
    )
    assert response.status_code == 400


def test_media_passes_through_416(tmp_path, monkeypatch):
    async def fake_open(client, url, headers=None, max_redirects=5, validator=None):
        return httpx.Response(416, headers={"content-range": "bytes */1000"})

    monkeypatch.setattr(main, "open_safe_stream", fake_open)
    client = make_client(tmp_path)
    response = client.get(
        "/api/media",
        params={"url": "https://v26-web.douyinvod.com/a.mp4"},
        headers={"Range": "bytes=5000-6000"},
    )
    assert response.status_code == 416


def test_slides_zip_rejects_index_out_of_range(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/slides/zip",
        json={
            "items": [
                {
                    "url": "https://p3-sign.douyinpic.com/a.webp",
                    "kind": "image",
                    "index": 10000,
                }
            ]
        },
    )
    assert response.status_code == 400


def test_media_rejects_html_on_416(tmp_path, monkeypatch):
    async def fake_open(client, url, headers=None, max_redirects=5, validator=None):
        return httpx.Response(
            416, content=b"<html>pwn</html>", headers={"content-type": "text/html"}
        )

    monkeypatch.setattr(main, "open_safe_stream", fake_open)
    client = make_client(tmp_path)
    response = client.get(
        "/api/media",
        params={"url": "https://v26-web.douyinvod.com/a.mp4"},
        headers={"Range": "bytes=5000-6000"},
    )
    assert response.status_code == 400


def test_slides_zip_rejects_zero_index(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/slides/zip",
        json={
            "items": [
                {
                    "url": "https://p3-sign.douyinpic.com/a.webp",
                    "kind": "image",
                    "index": 0,
                }
            ]
        },
    )
    assert response.status_code == 400
