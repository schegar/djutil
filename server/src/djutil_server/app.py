"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from . import __version__
from .auth import router as auth_router
from .config import Settings, get_settings
from .db import make_engine, run_migrations
from .library_api import router as library_router
from .live_api import router as live_router
from .live_api import stale_set_sweeper
from .services.live import LiveHub
from .sets_api import router as sets_router
from .sync_api import router as sync_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    app = FastAPI(title="DJUtil", version=__version__)
    app.state.settings = settings
    app.state.engine = make_engine(settings.db_path)
    app.state.hub = LiveHub()
    run_migrations(app.state.engine)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.cookie_secure,
        same_site="lax",
        max_age=30 * 24 * 3600,
    )

    app.include_router(auth_router)
    app.include_router(sync_router)
    app.include_router(library_router)
    app.include_router(live_router)
    app.include_router(sets_router)

    @app.on_event("startup")
    async def _sweeper() -> None:
        import asyncio

        app.state.sweeper_task = asyncio.create_task(stale_set_sweeper(app))

    @app.on_event("shutdown")
    async def _sweeper_stop() -> None:
        task = getattr(app.state, "sweeper_task", None)
        if task:
            task.cancel()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # Optional SPA serving: real files (Vite output lives under dist/assets)
    # then index.html fallback for non-/api paths.
    static_dir = settings.static_dir
    if static_dir and static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=assets),
                name="static-assets",
            )

        @app.exception_handler(404)
        async def spa_fallback(
            request: Request, exc: Exception
        ) -> JSONResponse | FileResponse:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (static_dir / request.url.path.lstrip("/")).resolve()
            if candidate.is_file() and candidate.is_relative_to(
                static_dir.resolve()
            ):
                return FileResponse(candidate)
            index = static_dir / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse({"detail": "Not Found"}, status_code=404)

    return app


app = create_app()
