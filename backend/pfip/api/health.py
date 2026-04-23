"""Health checks. Liveness (/health) + readiness (/health/deep)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from pfip.api.deps import DbSession, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness check. Always returns 200 if the app is up."""
    return {
        "status": "ok",
        "time": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/health/deep")
async def health_deep(db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    """Readiness check: pings TimescaleDB, Redis, Qdrant, Ollama."""
    checks: dict[str, Any] = {}

    # --- TimescaleDB ---
    try:
        result = await db.execute(text("SELECT 1"))
        checks["timescaledb"] = {"ok": result.scalar_one() == 1}
    except Exception as exc:  # noqa: BLE001
        checks["timescaledb"] = {"ok": False, "error": str(exc)}

    # --- Redis ---
    try:
        redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            pong = await redis.ping()
            checks["redis"] = {"ok": bool(pong)}
        finally:
            await redis.close()
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "error": str(exc)}

    # --- Qdrant ---
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.qdrant_url}/readyz")
            checks["qdrant"] = {"ok": resp.status_code == 200}
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = {"ok": False, "error": str(exc)}

    # --- Ollama ---
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            checks["ollama"] = {"ok": resp.status_code == 200}
    except Exception as exc:  # noqa: BLE001
        checks["ollama"] = {"ok": False, "error": str(exc)}

    all_ok = all(c.get("ok") for c in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "checks": checks,
    }
