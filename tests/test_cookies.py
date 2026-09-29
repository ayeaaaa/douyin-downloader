import pytest

from app import cookies

VALID = "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc123\n"


def test_status_unconfigured(tmp_path):
    assert cookies.cookie_status(str(tmp_path / "cookies.txt")) == {
        "configured": False,
        "entries": 0,
        "updated_at": None,
    }


def test_write_and_status(tmp_path):
    path = str(tmp_path / "cookies.txt")
    status = cookies.write_cookies(path, VALID)
    assert status["configured"] is True
    assert status["entries"] == 1
    assert (tmp_path / "cookies.txt").read_text(encoding="utf-8").endswith("\n")


def test_write_sets_private_permissions(tmp_path):
    path = tmp_path / "cookies.txt"
    cookies.write_cookies(str(path), VALID)
    assert (path.stat().st_mode & 0o777) == 0o600


def test_validate_rejects_empty():
    for content in ("", "   ", "# only a comment\n"):
        with pytest.raises(cookies.CookieError):
            cookies.validate_cookie_content(content)


def test_validate_rejects_bad_format():
    with pytest.raises(cookies.CookieError):
        cookies.validate_cookie_content(
            "# Netscape HTTP Cookie File\nnot a cookie line\n"
        )


def test_validate_accepts_httponly_lines():
    content = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tabc\n"
    )
    cookies.validate_cookie_content(content)


def test_validate_rejects_too_large():
    line = ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\t" + "x" * 100
    content = "# Netscape HTTP Cookie File\n" + (line + "\n") * 12000
    with pytest.raises(cookies.CookieError):
        cookies.validate_cookie_content(content)


def test_clear_cookies(tmp_path):
    path = tmp_path / "cookies.txt"
    cookies.write_cookies(str(path), VALID)
    cookies.clear_cookies(str(path))
    assert not path.exists()
    assert cookies.cookie_status(str(path))["configured"] is False
