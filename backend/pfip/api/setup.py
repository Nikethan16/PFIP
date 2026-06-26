"""First-run setup wizard endpoints.

Two routes:

- ``GET  /setup/status`` — returns the current onboarding state so the UI
  can decide whether to show the welcome wizard. Cheap; runs row-count
  queries only.

- ``POST /setup/bootstrap`` — idempotent. Seeds the default watchlist and
  kicks off the first wave of ingest flows. The frontend's welcome modal
  hits this on click; the user gets a single-button experience instead of
  needing to type docker exec commands.

Neither endpoint runs LLM calls or any external requests beyond what the
ingest flows themselves do. The ingest flows are run synchronously and
return per-flow row counts — slow (a few minutes) but simple. The frontend
keeps a spinner up while waiting; this avoids needing a separate job queue
just for first-run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from loguru import logger
from sqlalchemy import text

from pfip.api.deps import CurrentUser, DbSession
from pfip.scripts.seed_demo import clear_demo as _clear_demo
from pfip.scripts.seed_demo import seed_demo as _seed_demo
from pfip.scripts.seed_watchlist import _upsert_watchlist

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status")
async def setup_status(db: DbSession, _user: CurrentUser) -> dict[str, Any]:
    """Snapshot of onboarding state.

    Each field is a boolean signal the UI uses to decide what to prompt for.
    ``needs_setup`` is True if any P0 source has zero rows.
    """
    counts: dict[str, int] = {}
    for table in (
        "watchlist",
        "ohlcv",
        "mf_nav",
        "fx_rates",
        "macro_series",
        "news",
        "holdings",
        "source_health",
    ):
        try:
            row = (await db.execute(text(f"SELECT COUNT(*) AS n FROM {table}"))).mappings().first()
            counts[table] = int(row["n"]) if row else 0
        except Exception as exc:
            logger.debug(f"setup_status: table {table} count failed: {exc}")
            counts[table] = -1  # table missing or query failed

    needs_setup = counts.get("watchlist", 0) <= 0 or counts.get("ohlcv", 0) < 100
    return {
        "time": datetime.now(tz=UTC).isoformat(),
        "counts": counts,
        "needs_setup": needs_setup,
        "checklist": {
            "watchlist_seeded": counts.get("watchlist", 0) > 0,
            "crypto_ingested": counts.get("ohlcv", 0) >= 100,
            "mf_ingested": counts.get("mf_nav", 0) > 0,
            "fx_ingested": counts.get("fx_rates", 0) > 0,
            "macro_ingested": counts.get("macro_series", 0) > 0,
            "news_ingested": counts.get("news", 0) > 0,
            "holdings_added": counts.get("holdings", 0) > 0,
        },
    }


@router.post("/bootstrap")
async def bootstrap(_user: CurrentUser) -> dict[str, Any]:
    """One-button first-run: seed watchlist + run initial ingest flows.

    Synchronous. Takes a few minutes (mostly AMFI + FRED + Frankfurter
    network calls). Frontend should show a progress spinner. Returns
    per-step status. Idempotent — re-running is safe (watchlist seeds
    skip existing rows; ingests upsert).

    LLM keys are NOT required. Each step that doesn't have a configured
    API key is skipped with status "skipped".
    """
    started = datetime.now(tz=UTC)
    steps: list[dict[str, Any]] = []

    # ---- Step 1: seed watchlist ----
    try:
        added = await _upsert_watchlist()
        steps.append({"step": "seed_watchlist", "ok": True, "added": added})
    except Exception as exc:
        logger.warning(f"seed_watchlist failed: {exc}")
        steps.append({"step": "seed_watchlist", "ok": False, "error": str(exc)[:300]})

    # First-wave ingest — reuse the plain-async daily-pipeline ingest stage
    # (the Prefect ingest flows were retired). Non-fatal: each source inside is
    # individually guarded.
    try:
        from scripts.run_daily_pipeline import stage_ingest

        summ = await stage_ingest(include_news=True, include_fundamentals=True)
        steps.append({"step": "ingest", "ok": True, **summ.as_dict()})
    except Exception as exc:
        logger.warning(f"ingest failed: {exc}")
        steps.append({"step": "ingest", "ok": False, "error": str(exc)[:300]})
    elapsed = (datetime.now(tz=UTC) - started).total_seconds()
    return {
        "started_at": started.isoformat(),
        "elapsed_seconds": elapsed,
        "steps": steps,
        "ok": all(s.get("ok") for s in steps),
    }


@router.post("/demo")
async def seed_demo_endpoint(_user: CurrentUser) -> dict[str, Any]:
    """Populate every table with realistic synthetic data so the dashboard
    can be exercised end-to-end without waiting for real ingest.

    All inserted rows use the ``DEMO-*`` symbol prefix or ``source='demo'``
    so they can be removed cleanly via ``DELETE /api/v1/setup/demo``.

    Returns per-table row counts.
    """
    try:
        counts = await _seed_demo()
        return {
            "ok": True,
            "counts": counts,
            "note": (
                "Demo data inserted. Refresh the dashboard to see it. "
                "Remove anytime via DELETE /api/v1/setup/demo."
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.delete("/demo")
async def clear_demo_endpoint(_user: CurrentUser) -> dict[str, Any]:
    """Remove all rows previously inserted by /setup/demo. Idempotent."""
    try:
        counts = await _clear_demo()
        return {"ok": True, "deleted": counts}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
