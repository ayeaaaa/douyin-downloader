import httpx

from app import douyin


def test_is_douyin_url():
    assert douyin.is_douyin_url("https://v.douyin.com/abc/")
    assert douyin.is_douyin_url("https://www.douyin.com/video/123")
    assert douyin.is_douyin_url("https://www.iesdouyin.com/share/video/123")
    assert not douyin.is_douyin_url("https://douyin.com.evil.com/x")
    assert not douyin.is_douyin_url("https://example.com/x")


def test_fetch_ttwid_parses_set_cookie(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, headers={"set-cookie": "ttwid=abc123; Path=/; Domain=bytedance.com"}
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert douyin.fetch_ttwid() == "abc123"


def test_fetch_ttwid_returns_none_on_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("boom")

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert douyin.fetch_ttwid() is None


def test_ensure_cookies_keeps_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "cookies.txt"
    path.write_text("user cookies", encoding="utf-8")

    def fail():
        raise AssertionError("fetch_ttwid should not be called")

    monkeypatch.setattr(douyin, "fetch_ttwid", fail)
    assert douyin.ensure_cookies(str(path)) == str(path)
    assert path.read_text(encoding="utf-8") == "user cookies"


def test_ensure_cookies_generates_ttwid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "fetch_ttwid", lambda: "tok123")
    path = tmp_path / "cookies.txt"
    assert douyin.ensure_cookies(str(path)) == str(path)
    content = path.read_text(encoding="utf-8")
    assert "ttwid" in content
    assert "tok123" in content
    assert not (tmp_path / "cookies.txt.tmp").exists()


def test_ensure_cookies_returns_none_without_path():
    assert douyin.ensure_cookies(None) is None


def test_ensure_cookies_returns_none_on_unwritable_path(tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "fetch_ttwid", lambda: "tok123")
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    assert douyin.ensure_cookies(str(blocker / "cookies.txt")) is None


def test_apply_douyin_options_adds_referer_and_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "fetch_ttwid", lambda: "tok123")
    options = {"http_headers": {"X-Test": "1"}}
    douyin.apply_douyin_options(
        options, "https://v.douyin.com/x/", str(tmp_path / "cookies.txt")
    )
    assert options["http_headers"] == {
        "X-Test": "1",
        "Referer": douyin.DOUYIN_REFERER,
    }
    assert options["cookiefile"] == str(tmp_path / "cookies.txt")


def test_apply_douyin_options_ignores_other_platforms():
    options = {}
    douyin.apply_douyin_options(options, "https://example.com/x", "/tmp/x.txt")
    assert options == {}


def test_apply_douyin_options_creates_no_file_for_other_platforms(tmp_path):
    path = tmp_path / "cookies.txt"
    douyin.apply_douyin_options({}, "https://example.com/x", str(path))
    assert not path.exists()


def test_load_cookie_dict_parses_netscape(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc\n"
        "#HttpOnly_.douyin.com\tTRUE\t/\tFALSE\t0\tsid\txyz\n",
        encoding="utf-8",
    )
    assert douyin.load_cookie_dict(str(path)) == {"ttwid": "abc", "sid": "xyz"}


def test_load_cookie_dict_missing_file(tmp_path):
    assert douyin.load_cookie_dict(str(tmp_path / "none.txt")) == {}


def test_build_slides_items_maps_images_clips_music():
    detail = {
        "images": [
            {
                "url_list": ["https://img/1.webp"],
                "download_url_list": ["https://img/1-orig.webp"],
            },
            {
                "url_list": ["https://img/2.webp"],
                "video": {"play_addr": {"url_list": ["https://v/2.mp4"]}},
            },
        ],
        "music": {"play_url": {"uri": "https://m/bgm.mp3"}},
    }
    assert douyin.build_slides_items(detail) == [
        {
            "kind": "image",
            "index": 1,
            "preview_url": "https://img/1.webp",
            "download_url": "https://img/1-orig.webp",
        },
        {
            "kind": "clip",
            "index": 2,
            "preview_url": "https://img/2.webp",
            "download_url": "https://v/2.mp4",
        },
        {
            "kind": "music",
            "index": 1,
            "preview_url": "https://m/bgm.mp3",
            "download_url": "https://m/bgm.mp3",
        },
    ]


def test_build_slides_items_skips_empty_images():
    detail = {"images": [{"url_list": []}, {"url_list": ["https://img/2.webp"]}]}
    items = douyin.build_slides_items(detail)
    assert [item["kind"] for item in items] == ["image"]
    assert items[0]["index"] == 2


def test_extract_slides_success(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "ensure_cookies", lambda path: None)
    monkeypatch.setattr(douyin, "load_cookie_dict", lambda path: {})

    def handler(request):
        return httpx.Response(
            200,
            json={
                "aweme_detail": {
                    "desc": "图文标题",
                    "author": {"nickname": "作者"},
                    "images": [
                        {
                            "url_list": ["https://img/1.webp"],
                            "download_url_list": ["https://img/1o.webp"],
                        }
                    ],
                    "music": {"play_url": {"uri": "https://m/bgm.mp3"}},
                }
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = douyin.extract_slides(
        "123", str(tmp_path / "cookies.txt"), "https://v.douyin.com/x/"
    )
    assert result["ok"] is True
    assert result["media_type"] == "slides"
    assert result["title"] == "图文标题"
    assert result["author"] == "作者"
    assert result["cover"] == "https://img/1.webp"
    assert len(result["items"]) == 2


def test_extract_slides_risk_control(monkeypatch):
    monkeypatch.setattr(douyin, "ensure_cookies", lambda path: None)
    monkeypatch.setattr(douyin, "load_cookie_dict", lambda path: {})

    def handler(request):
        return httpx.Response(403, text="Blocked by ArgusSecurityPlugin")

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = douyin.extract_slides("123", None, "https://v.douyin.com/x/")
    assert result["ok"] is False
    assert "风控" in result["error"]


def test_resolve_douyin_url_follows_redirect(monkeypatch):
    def handler(request):
        if request.url.host == "v.douyin.com":
            return httpx.Response(
                302,
                headers={"location": "https://www.iesdouyin.com/share/slides/123/"},
            )
        return httpx.Response(200, content=b"<html></html>")

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(douyin, "is_safe_public_url", lambda url: True)
    assert (
        douyin.resolve_douyin_url("https://v.douyin.com/x/")
        == "https://www.iesdouyin.com/share/slides/123/"
    )


def test_resolve_douyin_url_rejects_private_redirect(monkeypatch):
    def handler(request):
        if request.url.host == "v.douyin.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/x"})
        return httpx.Response(200, content=b"x")

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(
        douyin,
        "is_safe_public_url",
        lambda url: not url.startswith("http://127.0.0.1"),
    )
    assert (
        douyin.resolve_douyin_url("https://v.douyin.com/x/")
        == "https://v.douyin.com/x/"
    )


def test_extract_slides_non_dict_json(monkeypatch):
    monkeypatch.setattr(douyin, "ensure_cookies", lambda path: None)
    monkeypatch.setattr(douyin, "load_cookie_dict", lambda path: {})

    def handler(request):
        return httpx.Response(200, json=["not", "a", "dict"])

    real_client = httpx.Client
    monkeypatch.setattr(
        douyin.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = douyin.extract_slides("123", None, "https://v.douyin.com/x/")
    assert result["ok"] is False
