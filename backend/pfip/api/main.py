"""FastAPI entrypoint for the PFIP backend.

Bootstraps logging, mounts CORS, and includes every router under ``/api/v1``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from pfip import __version__
from pfip.api import (
    agent,
    assets,
    auth,
    backtest,
    calibration,
    changes_today,
    health,
    journal,
    model_registry,
    notifications,
    portfolio,
    schedules,
    settings as settings_router,
    setup,
    shadow,
    signals,
    tax,
    watchlist,
)
from pfip.core.config import get_settings
from pfip.core.contracts import ProblemDetail
from pfip.core.logging import configure_logging, get_logger


def _init_sentry(settings) -> None:  # noqa: ANN001
    """Initialize Sentry if a DSN is configured. Optional dependency.

    Never fails startup: a missing ``sentry-sdk`` or a bad init is logged and
    swallowed so the API still boots.
    """
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk  # type: ignore
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping error tracking.")
        return
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=0.1,
        )
        logger.info("Sentry error tracking initialized.")
    except Exception as exc:  # noqa: BLE001 — never block startup on Sentry
        logger.warning(f"Sentry init failed ({exc}); continuing without error tracking.")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger("pfip.api")
    log.info(f"PFIP backend v{__version__} starting")
    yield
    log.info("PFIP backend shutting down")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    _init_sentry(settings)
    app = FastAPI(
        title="PFIP Backend",
        version=__version__,
        description="Personal Financial Intelligence Platform — hedge-fund-in-a-box.",
        lifespan=_lifespan,
    )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all 500 handler.

        Logs the full exception server-side (with stack trace) but returns a
        generic RFC-7807 problem+json body — never leaking internals or the
        traceback to the client.
        """
        logger.opt(exception=exc).error(
            f"Unhandled exception on {request.method} {request.url.path}: {exc!r}"
        )
        problem = ProblemDetail(
            type="about:blank",
            title="Internal Server Error",
            status=500,
            detail="An unexpected error occurred. The incident has been logged.",
            instance=str(request.url.path),
        )
        return JSONResponse(
            status_code=500,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # All routers live under /api/v1
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(assets.router, prefix=prefix)
    app.include_router(watchlist.router, prefix=prefix)
    app.include_router(signals.router, prefix=prefix)
    app.include_router(portfolio.router, prefix=prefix)
    app.include_router(shadow.router, prefix=prefix)
    app.include_router(backtest.router, prefix=prefix)
    app.include_router(calibration.router, prefix=prefix)
    app.include_router(tax.router, prefix=prefix)
    app.include_router(agent.router, prefix=prefix)
    app.include_router(journal.router, prefix=prefix)
    app.include_router(setup.router, prefix=prefix)
    app.include_router(model_registry.router, prefix=prefix)
    app.include_router(changes_today.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(schedules.router, prefix=prefix)
    app.include_router(settings_router.router, prefix=prefix)

    return app


app = create_app()
