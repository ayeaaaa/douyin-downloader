import asyncio

import httpx

from app import http_safe


def _allow_only(monkeypatch, allowed_host):
    monkeypatch.setattr(
        http_safe,
        "is_safe_public_url",
        lambda url: httpx.URL(url).host == allowed_host,
    )


def test_safe_get_sync_follows_valid_redirect(monkeypatch):
    _allow_only(monkeypatch, "example.com")

    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = http_safe.safe_get_sync(client, "https://example.com/a")
    assert response is not None
    assert response.status_code == 200
    assert response.content == b"ok"


def test_safe_get_sync_rejects_unsafe_redirect(monkeypatch):
    _allow_only(monkeypatch, "example.com")

    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"secret")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = http_safe.safe_get_sync(client, "https://example.com/a")
    assert response is None


def test_safe_get_sync_stops_after_max_redirects(monkeypatch):
    _allow_only(monkeypatch, "example.com")

    def handler(request):
        return httpx.Response(302, headers={"location": "/loop"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = http_safe.safe_get_sync(client, "https://example.com/a")
    assert response is None


def test_safe_get_async_follows_valid_redirect(monkeypatch):
    _allow_only(monkeypatch, "example.com")

    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, content=b"ok")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await http_safe.safe_get_async(client, "https://example.com/a")

    response = asyncio.run(run())
    assert response is not None
    assert response.status_code == 200


def test_safe_get_async_rejects_unsafe_redirect(monkeypatch):
    _allow_only(monkeypatch, "example.com")

    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://192.168.1.1/x"})
        return httpx.Response(200, content=b"secret")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await http_safe.safe_get_async(client, "https://example.com/a")

    assert asyncio.run(run()) is None


def test_open_safe_stream_follows_valid_redirect(monkeypatch):
    _allow_only(monkeypatch, "example.com")

    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, content=b"ok")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await http_safe.open_safe_stream(client, "https://example.com/a")
            content = await response.aread()
            await response.aclose()
            return response.status_code, content

    assert asyncio.run(run()) == (200, b"ok")


def test_open_safe_stream_rejects_unsafe_redirect_target(monkeypatch):
    monkeypatch.setattr(
        http_safe,
        "is_safe_public_url",
        lambda url: True,
    )

    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/x"})
        return httpx.Response(200, content=b"secret")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await http_safe.open_safe_stream(
                client,
                "https://example.com/a",
                validator=lambda url: not url.startswith("http://127.0.0.1"),
            )

    assert asyncio.run(run()) is None
