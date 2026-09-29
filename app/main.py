import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import downloader, extractor
from .http_safe import safe_get_async
from .security import BasicAuthMiddleware, is_allowed_cover_url, sanitize_filename

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_TEMP_DIR = "/tmp/douyin-dl"
MAX_BODY_BYTES = 64 * 1024


@dataclass
class Settings:
    access_password: str = ""
    max_filesize_mb: int = 500
    cookies_path: str = "/data/cookies.txt"
    temp_dir: str = DEFAULT_TEMP_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            access_password=os.environ.get("ACCESS_PASSWORD", ""),
            max_filesize_mb=int(os.environ.get("MAX_FILESIZE_MB", "500")),
            cookies_path=os.environ.get("COOKIES_PATH", "/data/cookies.txt"),
            temp_dir=os.environ.get("TEMP_DIR", DEFAULT_TEMP_DIR),
        )


async def _file_chunks(path: Path, chunk_size: int = 65536):
    with open(path, "rb") as file:
        while True:
            chunk = file.read(chunk_size)
            if not chunk:
                break
            yield chunk


class _RelayResponse(StreamingResponse):
    def __init__(
        self,
        path: Path,
        job_dir: str,
        semaphore: asyncio.Semaphore,
        media_type: str,
        headers: dict,
    ):
        super().__init__(_file_chunks(path), media_type=media_type, headers=headers)
        self._job_dir = job_dir
        self._semaphore = semaphore
        self._released = False

    def _release(self) -> None:
        if self._released:
            return
        self._released = True
        downloader.cleanup_dir(self._job_dir)
        self._semaphore.release()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                length = 0
            if length > self.max_bytes:
                return JSONResponse({"error": "请求体过大"}, status_code=413)
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)
    downloader.cleanup_stale(settings.temp_dir)

    app = FastAPI(title="Douyin Downloader")
    app.state.download_semaphore = asyncio.Semaphore(1)
    app.state.parse_semaphore = asyncio.Semaphore(2)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)

    if settings.access_password:
        app.add_middleware(BasicAuthMiddleware, password=settings.access_password)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/api/parse")
    async def api_parse(payload: dict):
        text = (payload or {}).get("text") or ""
        if len(text) > 20000:
            return JSONResponse({"error": "内容过长,请减少链接数量"}, status_code=400)
        urls = extractor.extract_urls(text)
        if not urls:
            return JSONResponse(
                {"error": "未找到链接,请粘贴视频链接或分享文案"}, status_code=400
            )
        if len(urls) > 20:
            return JSONResponse({"error": "一次最多解析 20 条链接"}, status_code=400)
        results = []
        for url in urls:
            async with app.state.parse_semaphore:
                results.append(
                    await asyncio.to_thread(
                        extractor.parse_url, url, settings.cookies_path
                    )
                )
        return {"results": results}

    @app.get("/api/download")
    async def api_download(url: str = Query(...)):
        semaphore = app.state.download_semaphore
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
        except asyncio.TimeoutError:
            return JSONResponse(
                {"error": "已有下载任务进行中,请稍后重试"}, status_code=429
            )

        job_dir = None
        handed_off = False
        try:
            job_dir = tempfile.mkdtemp(dir=settings.temp_dir, prefix="job-")
            try:
                path, title = await asyncio.to_thread(
                    downloader.download_to_temp,
                    url,
                    job_dir,
                    settings.cookies_path,
                    settings.max_filesize_mb,
                )
            except downloader.DownloadError as exc:
                return JSONResponse(
                    {"error": extractor.humanize_error(exc)}, status_code=502
                )
            filename = sanitize_filename(title) + path.suffix
            response = _RelayResponse(
                path,
                job_dir,
                semaphore,
                media_type="video/mp4",
                headers={
                    "Content-Disposition": "attachment; filename*=utf-8''"
                    + quote(filename),
                    "Content-Length": str(path.stat().st_size),
                },
            )
            handed_off = True
            return response
        finally:
            if not handed_off:
                if job_dir is not None:
                    downloader.cleanup_dir(job_dir)
                semaphore.release()

    @app.get("/api/cover")
    async def api_cover(url: str = Query(...)):
        if not is_allowed_cover_url(url):
            return JSONResponse({"error": "不允许的封面地址"}, status_code=400)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await safe_get_async(client, url)
        except (httpx.HTTPError, httpx.InvalidURL):
            return JSONResponse({"error": "封面获取失败"}, status_code=502)
        if response is None or response.status_code != 200:
            return JSONResponse({"error": "封面获取失败"}, status_code=502)
        return Response(
            content=response.content,
            media_type=response.headers.get("content-type", "image/jpeg"),
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="site")
    return app


app = create_app()
