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
