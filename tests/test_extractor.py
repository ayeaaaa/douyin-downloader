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
