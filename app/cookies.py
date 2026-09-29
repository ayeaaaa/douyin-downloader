import os
import tempfile
from pathlib import Path

MAX_COOKIE_BYTES = 1024 * 1024


class CookieError(Exception):
    pass


def _data_lines(content: str) -> list[str]:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#HttpOnly_"):
            lines.append(line)
        elif not stripped.startswith("#"):
            lines.append(line)
    return lines


def cookie_status(cookies_path: str | None) -> dict:
    empty = {"configured": False, "entries": 0, "updated_at": None}
    if not cookies_path:
        return empty
    path = Path(cookies_path)
    try:
        if not path.is_file():
            return empty
        content = path.read_text(encoding="utf-8", errors="replace")
        updated_at = int(path.stat().st_mtime)
    except OSError:
        return empty
    return {
        "configured": True,
        "entries": len(_data_lines(content)),
        "updated_at": updated_at,
    }


def validate_cookie_content(content: str) -> None:
    if not content or not content.strip():
        raise CookieError("内容为空")
    if len(content.encode("utf-8")) > MAX_COOKIE_BYTES:
        raise CookieError("文件过大(超过 1MB)")
    data_lines = _data_lines(content)
    if not data_lines:
        raise CookieError("未找到 cookie 条目,请使用 Netscape 格式的 cookies.txt")
    for line in data_lines:
        if len(line.split("\t")) < 7:
            raise CookieError("格式不正确,请使用 Netscape 格式的 cookies.txt")


def write_cookies(cookies_path: str, content: str) -> dict:
    validate_cookie_content(content)
    path = Path(cookies_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
    except OSError as exc:
        raise CookieError(f"保存失败:{exc}") from exc
    normalized = content if content.endswith("\n") else content + "\n"
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(normalized)
        os.replace(temp_name, path)
    except OSError as exc:
        raise CookieError(f"保存失败:{exc}") from exc
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
    return cookie_status(cookies_path)


def clear_cookies(cookies_path: str | None) -> None:
    if not cookies_path:
        return
    try:
        Path(cookies_path).unlink(missing_ok=True)
    except OSError as exc:
        raise CookieError(f"清除失败:{exc}") from exc
