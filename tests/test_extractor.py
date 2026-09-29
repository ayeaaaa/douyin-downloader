import httpx

from app import extractor


def test_extract_urls_from_share_text():
    text = (
        "7.28 复制打开抖音，看看【作者的作品】 "
        "https://v.douyin.com/iAbCdEf/ 复制此链接，打开Dou音搜索"
    )
    assert extractor.extract_urls(text) == ["https://v.douyin.com/iAbCdEf/"]


def test_extract_urls_multiple_dedupe_preserves_order():
    text = (
        "https://v.douyin.com/a/ 和 https://www.douyin.com/video/123 ，"
        "还有 https://v.douyin.com/a/"
    )
    assert extractor.extract_urls(text) == [
        "https://v.douyin.com/a/",
        "https://www.douyin.com/video/123",
    ]


def test_extract_urls_trims_chinese_punctuation():
    assert extractor.extract_urls("看这个 https://v.douyin.com/x/。") == [
        "https://v.douyin.com/x/"
    ]


def test_extract_urls_none():
    assert extractor.extract_urls("没有链接") == []


def test_humanize_error_login():
    error = Exception("Sign in to confirm you are not a bot")
    assert extractor.humanize_error(error) == "需要登录,请配置 cookies.txt"


def test_humanize_error_unsupported():
    assert extractor.humanize_error(Exception("Unsupported URL: x")) == "不支持的链接"


def test_pick_direct_format_prefers_progressive_mp4():
    info = {
        "formats": [
            {
                "url": "https://cdn/a.m3u8",
                "ext": "mp4",
                "vcodec": "h264",
                "acodec": "none",
                "height": 1080,
            },
            {
                "url": "https://cdn/b.mp4",
                "ext": "mp4",
                "vcodec": "h264",
                "acodec": "aac",
                "height": 720,
                "http_headers": {"User-Agent": "x"},
            },
            {
                "url": "https://cdn/c.mp4",
                "ext": "mp4",
                "vcodec": "h264",
                "acodec": "aac",
                "height": 480,
            },
        ]
    }
    url, headers = extractor.pick_direct_format(info)
    assert url == "https://cdn/b.mp4"
    assert headers == {"User-Agent": "x"}


def test_pick_direct_format_none_when_only_split_streams():
    info = {
        "formats": [
            {
                "url": "https://cdn/a.mp4",
                "ext": "mp4",
                "vcodec": "h264",
                "acodec": "none",
            }
        ]
    }
    assert extractor.pick_direct_format(info) == (None, {})


def test_parse_url_success(monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            assert download is False
            return {
                "title": "测试视频",
                "uploader": "作者",
                "thumbnail": "https://p3-sign.douyinpic.com/t.jpg",
                "duration": 15,
                "formats": [
                    {
                        "url": "https://cdn/v.mp4",
                        "ext": "mp4",
                        "vcodec": "h264",
                        "acodec": "aac",
                        "height": 720,
                    }
                ],
            }

    monkeypatch.setattr(extractor.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(extractor, "is_safe_public_url", lambda url: True)
    monkeypatch.setattr(extractor, "probe_direct", lambda url, headers: True)

    result = extractor.parse_url("https://v.douyin.com/x/")

    assert result["ok"] is True
    assert result["title"] == "测试视频"
    assert result["author"] == "作者"
    assert result["duration"] == 15
    assert result["direct_url"] == "https://cdn/v.mp4"
    assert result["direct_ok"] is True
    assert result["error"] is None


def test_parse_url_error_isolated(monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("Sign in to confirm you are not a bot")

    monkeypatch.setattr(extractor.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(extractor, "is_safe_public_url", lambda url: True)

    result = extractor.parse_url("https://v.douyin.com/x/")

    assert result["ok"] is False
    assert result["error"] == "需要登录,请配置 cookies.txt"


def test_parse_url_rejects_unsafe_url(monkeypatch):
    monkeypatch.setattr(extractor, "is_safe_public_url", lambda url: False)
    result = extractor.parse_url("http://127.0.0.1/x")
    assert result["ok"] is False
    assert result["error"] == "不支持的链接"


def test_probe_direct_follows_redirect_and_returns_true(monkeypatch):
    def handler(request):
        if request.url.path == "/video":
            return httpx.Response(
                302, headers={"location": "https://cdn.example.com/v.mp4"}
            )
        return httpx.Response(206, headers={"content-range": "bytes 0-0/1000"})

    real_client = httpx.Client
    monkeypatch.setattr(
        extractor.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(extractor, "is_safe_public_url", lambda url: True)
    assert extractor.probe_direct("https://cdn.example.com/video", {}) is True


def test_probe_direct_rejects_redirect_to_private(monkeypatch):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    real_client = httpx.Client
    monkeypatch.setattr(
        extractor.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(
        extractor,
        "is_safe_public_url",
        lambda url: not url.startswith("http://127.0.0.1"),
    )
    assert extractor.probe_direct("https://cdn.example.com/video", {}) is False
