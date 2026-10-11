"""FastAPI 앱. `uvicorn app.main:create_app --factory` 또는 `python -m app serve`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes import router
from .context import AppContext, build_context
from .core.config import Settings, load_settings
from .extraction.reviews import ReviewError, ReviewNotFound
from .occurrences.actions import WriteFailed
from .occurrences.items import ItemNotFound
from .occurrences.service import OccurrenceNotFound

log = logging.getLogger(__name__)


class WebFiles(StaticFiles):
    """빌드된 화면. index.html 등은 매번 확인(no-cache), 해시가 붙은 assets/는 오래 캐시한다.

    헤더가 없으면 브라우저가 index.html을 임의로 캐시해서, 배포 뒤 사라진 옛 번들을 찾다 빈 화면이 된다.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        resp = await super().get_response(path, scope)
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def create_app(settings: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    settings = ctx.settings if ctx else (settings or load_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = ctx or build_context(settings)
        app.state.ctx = c
        c.start()
        log.info("시작: data=%s llm=%s", settings.data_dir, settings.llm_mode)
        try:
            yield
        finally:
            c.stop()

    app = FastAPI(
        title="공유형 개인 비서 API",
        version=__version__,
        description="노트 기반 일정 추적. 모든 경로는 /api/v1 아래. 인증은 Authorization: Bearer <기기 토큰>.",
        lifespan=lifespan,
    )
    app.include_router(router)

    def not_found(_: Request, exc: Exception):
        return JSONResponse(status_code=404, content={"detail": "찾을 수 없어요", "id": str(exc)})

    for exc_type in (OccurrenceNotFound, ItemNotFound, ReviewNotFound):
        app.add_exception_handler(exc_type, not_found)

    @app.exception_handler(ReviewError)
    def review_error(_: Request, exc: ReviewError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(WriteFailed)
    def write_failed(_: Request, exc: WriteFailed):
        return JSONResponse(status_code=409, content={"detail": str(exc), "review_id": exc.review_id})

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    if settings.web_dist.exists():
        app.mount("/", WebFiles(directory=settings.web_dist, html=True), name="web")
    return app
