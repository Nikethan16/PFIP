"""Health checks. Liveness (/health) + readiness (/health/deep) + providers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from pfip.api.deps import DbSession, SettingsDep
from pfip.core.config import Settings

router = APIRouter(tags=["health"])


# ---------------------------------------------------------------------------
# Provider health probes
# ---------------------------------------------------------------------------


async def _probe_groq(api_key: str) -> dict[str, Any]:
    if not api_key:
        return {"status": "unconfigured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_gemini(api_key: str) -> dict[str, Any]:
    if not api_key:
        return {"status": "unconfigured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            )
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_deepseek(api_key: str) -> dict[str, Any]:
    if not api_key:
        return {"status": "unconfigured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.deepseek.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_openrouter(api_key: str) -> dict[str, Any]:
    if not api_key:
        return {"status": "unconfigured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_nim(api_key: str) -> dict[str, Any]:
    if not api_key:
        return {"status": "unconfigured"}
    # NVIDIA NIM uses an OpenAI-compatible endpoint at integrate.api.nvidia.com.
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://integrate.api.nvidia.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_cohere(api_key: str) -> dict[str, Any]:
    if not api_key:
        return {"status": "unconfigured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.cohere.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_ollama(host: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{host}/api/tags")
        return {"status": "ok" if resp.status_code == 200 else "fail", "code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"status": "fail", "error": str(exc)[:200]}


async def _probe_all_providers(settings: Settings) -> dict[str, dict[str, Any]]:
    """Probe every configured provider. Returns ``{name: {status, ...}}``."""
    return {
        "groq": await _probe_groq(settings.groq_api_key),
        "gemini": await _probe_gemini(settings.gemini_api_key),
        "deepseek": await _probe_deepseek(settings.deepseek_api_key),
        "openrouter": await _probe_openrouter(settings.openrouter_api_key),
        "nvidia_nim": await _probe_nim(settings.nvidia_nim_api_key),
        "cohere": await _probe_cohere(settings.cohere_api_key),
        "ollama": await _probe_ollama(settings.ollama_host),
    }


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
    # Qdrant Cloud needs a real round-trip (2s was too tight and produced false
    # ok=false) and sends the api-key header on authenticated deployments. We
    # report the status code / error so a genuine failure is diagnosable.
    try:
        qdrant_headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(f"{settings.qdrant_url}/readyz", headers=qdrant_headers)
            checks["qdrant"] = {"ok": resp.status_code == 200, "code": resp.status_code}
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = {"ok": False, "error": str(exc)[:200]}

    # --- Ollama ---
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            checks["ollama"] = {"ok": resp.status_code == 200}
    except Exception as exc:  # noqa: BLE001
        checks["ollama"] = {"ok": False, "error": str(exc)}

    # --- LLM providers (summary) ---
    try:
        providers = await _probe_all_providers(settings)
        configured = {k: v for k, v in providers.items() if v.get("status") != "unconfigured"}
        any_ok = any(v.get("status") == "ok" for v in configured.values()) if configured else True
        checks["llm_providers"] = {
            "ok": any_ok,
            "configured": list(configured.keys()),
            "summary": {k: v.get("status") for k, v in providers.items()},
        }
    except Exception as exc:  # noqa: BLE001
        checks["llm_providers"] = {"ok": False, "error": str(exc)}

    # Weight core dependencies (the app cannot serve without them) separately
    # from optional ones (Qdrant/Ollama/cloud providers). A local run with the
    # vector store or LLM down is "degraded" but still ready, not "down".
    core = ("timescaledb", "redis")
    core_ok = all(checks.get(name, {}).get("ok") for name in core)
    all_ok = all(c.get("ok") for c in checks.values())
    if not core_ok:
        status = "down"
    elif all_ok:
        status = "ok"
    else:
        status = "degraded"
    return {
        "status": status,
        "ready": core_ok,
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "checks": checks,
    }


@router.get("/health/providers")
async def health_providers(settings: SettingsDep) -> dict[str, Any]:
    """Ping each configured LLM provider with a minimal request.

    Returns ``{provider: {status: ok|fail|unconfigured, ...}}`` for the
    full multi-provider set. The router (``pfip.agent.router``) picks
    providers from this set at runtime; ``unconfigured`` ones are simply
    skipped in the fallback chain.
    """
    providers = await _probe_all_providers(settings)
    return {
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "providers": providers,
    }


# ---------------------------------------------------------------------------
# Per-data-source freshness — reads from the `source_health` table populated
# by every ingest flow's `record_run()` call. Powers UI freshness badges.
# ---------------------------------------------------------------------------


@router.get("/health/sources")
async def health_sources(db: DbSession) -> dict[str, Any]:
    """Report each ingest source's last-run timestamp, last row count, and
    consecutive-failure streak. The UI consumes this to render stale-data
    badges and the Settings → Schedules page.

    Each row has:
        source: adapter name (e.g. "ccxt_multi", "amfi_nav", "frankfurter")
        last_run_at: ISO-8601 timestamp of most recent run attempt
        last_success_at: most recent successful run; null if never succeeded
        last_rows: row count from the most recent run
        last_error: error message if last run failed (else null)
        consecutive_failures: how many failures in a row (0 means healthy)
        stale_seconds: how long since last successful run, or null
        status: "healthy" | "stale" | "failing" | "never_run"
    """
    now = datetime.now(tz=timezone.utc)
    try:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        source, last_run_at, last_success_at, last_rows,
                        last_error, consecutive_failures, updated_at
                    FROM source_health
                    ORDER BY last_run_at DESC
                    """
                )
            )
        ).mappings()
    except Exception as exc:  # noqa: BLE001
        # source_health may not exist yet on fresh installs (pre-migration 0006)
        return {
            "time": now.isoformat(),
            "sources": [],
            "summary": {"error": str(exc)[:300]},
        }

    sources: list[dict[str, Any]] = []
    n_healthy = n_stale = n_failing = 0
    for r in rows:
        last_success = r["last_success_at"]
        consec = int(r["consecutive_failures"] or 0)
        if last_success is None:
            stale_seconds: float | None = None
            status = "never_run" if consec == 0 else "failing"
        else:
            stale_seconds = (now - last_success).total_seconds()
            # Threshold: > 2 days since success = stale
            if consec > 0:
                status = "failing"
            elif stale_seconds > 172800:  # 2 days
                status = "stale"
            else:
                status = "healthy"
        if status == "healthy":
            n_healthy += 1
        elif status == "stale":
            n_stale += 1
        elif status == "failing":
            n_failing += 1
        sources.append(
            {
                "source": r["source"],
                "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None,
                "last_success_at": last_success.isoformat() if last_success else None,
                "last_rows": r["last_rows"],
                "last_error": r["last_error"],
                "consecutive_failures": consec,
                "stale_seconds": stale_seconds,
                "status": status,
            }
        )
    return {
        "time": now.isoformat(),
        "sources": sources,
        "summary": {
            "total": len(sources),
            "healthy": n_healthy,
            "stale": n_stale,
            "failing": n_failing,
        },
    }
