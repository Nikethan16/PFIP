"""FastAPI entrypoint for the PFIP backend.

Bootstraps logging, mounts CORS, and includes every router under ``/api/v1``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pfip import __version__
from pfip.api import (
    agent,
    assets,
    auth,
    calibration,
    health,
    journal,
    portfolio,
    shadow,
    signals,
    tax,
    watchlist,
)
from pfip.core.config import get_settings
from pfip.core.logging import configure_logging, get_logger


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
    app = FastAPI(
        title="PFIP Backend",
        version=__version__,
        description="Personal Financial Intelligence Platform — hedge-fund-in-a-box.",
        lifespan=_lifespan,
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
    app.include_router(calibration.router, prefix=prefix)
    app.include_router(tax.router, prefix=prefix)
    app.include_router(agent.router, prefix=prefix)
    app.include_router(journal.router, prefix=prefix)

    return app


app = create_app()
