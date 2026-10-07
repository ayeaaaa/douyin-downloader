import socket

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.security import (
    BasicAuthMiddleware,
    is_allowed_cover_url,
    is_allowed_media_url,
    is_safe_public_url,
    sanitize_filename,
)


def test_sanitize_filename_strips_path_and_illegal_chars():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_filename_keeps_chinese_and_truncates():
    cleaned = sanitize_filename("抖音视频" * 40)
    assert cleaned.startswith("抖音视频")
    assert len(cleaned) <= 120


def test_sanitize_filename_empty_fallback():
    assert sanitize_filename("   ") == "video"
    assert sanitize_filename("...") == "video"


def test_safe_public_url_rejects_private_and_bad_scheme():
    assert not is_safe_public_url("ftp://example.com/a")
    assert not is_safe_public_url("http://127.0.0.1/a")
    assert not is_safe_public_url("http://192.168.1.10/a")
    assert not is_safe_public_url("http://100.64.0.1/a")


def test_safe_public_url_rejects_malformed_ipv6():
    assert is_safe_public_url("http://[::1") is False


def test_safe_public_url_rejects_invalid_port():
    assert is_safe_public_url("http://example.com:abc/") is False


def test_safe_public_url_rejects_invalid_idna_hostname():
    assert is_safe_public_url("http://" + "ü" * 60 + ".com/") is False


def test_safe_public_url_accepts_public(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    assert is_safe_public_url("https://example.com/video")


def test_allowed_cover_url(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    assert is_allowed_cover_url("https://p3-sign.douyinpic.com/a.jpg")
    assert not is_allowed_cover_url("https://evil.com/a.jpg")
    assert not is_allowed_cover_url("https://douyin.com.evil.com/a.jpg")


def test_allowed_cover_url_rejects_invalid_port():
    assert is_allowed_cover_url("https://p3-sign.douyinpic.com:abc/a.jpg") is False


def test_allowed_cover_url_rejects_invalid_idna_hostname():
    assert (
        is_allowed_cover_url("https://" + "ü" * 60 + ".com.douyinpic.com/a.jpg")
        is False
    )


def test_allowed_media_url(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    assert is_allowed_media_url("https://v26-web.douyinvod.com/video/x.mp4")
    assert is_allowed_media_url("https://p3-sign.douyinpic.com/a.webp")
    assert is_allowed_media_url("https://sf6-cdn-tos.douyinstatic.com/obj/x.mp3")
    assert not is_allowed_media_url("https://evil.com/a.mp4")
    assert not is_allowed_media_url("https://douyinvod.com.evil.com/a.mp4")
    assert not is_allowed_media_url("http://[::1")


def test_basic_auth_middleware():
    async def homepage(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/", homepage), Route("/healthz", homepage)])
    inner.add_middleware(BasicAuthMiddleware, password="secret")
    client = TestClient(inner)
    assert client.get("/").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.get("/", auth=("any", "wrong")).status_code == 401
    assert client.get("/", auth=("any", "secret")).status_code == 200


def test_basic_auth_middleware_non_ascii_password():
    async def homepage(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/", homepage)])
    inner.add_middleware(BasicAuthMiddleware, password="密码")
    client = TestClient(inner)
    assert client.get("/", auth=("any", "密码")).status_code == 200
    assert client.get("/", auth=("any", "wrong")).status_code == 401
