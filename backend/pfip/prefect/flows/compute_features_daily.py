"""Daily feature-compute flow (06:00 IST, post-ingest).

Iterates every watchlist asset, runs the full feature pipeline
(:func:`pfip.features.runner.compute_and_persist`), and upserts into the
``features`` table. Falls back to BTC/USD if the watchlist is empty so
operators can hand-run the flow and still get useful telemetry.

Run manually:

    python -m pfip.prefect.flows.compute_features_daily
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task

from pfip.db.session import get_sessionmaker
from pfip.features.runner import (
    FeatureRunRequest,
    FeatureRunResult,
    compute_and_persist,
    run_for_watchlist,
)


@task(name="features-default-symbol")
async def _run_default(symbol: str, source: str, timeframe: str) -> FeatureRunResult:
    factory = get_sessionmaker()
    async with factory() as session:
        req = FeatureRunRequest(symbol=symbol, source=source, timeframe=timeframe)
        return await compute_and_persist(session, req)


@task(name="features-watchlist")
async def _run_watchlist(timeframe: str) -> list[FeatureRunResult]:
    factory = get_sessionmaker()
    async with factory() as session:
        return await run_for_watchlist(session, timeframe=timeframe)


@flow(name="compute-features-daily", log_prints=True)
async def compute_features_daily(
    *,
    fallback_symbol: str = "BTC/USD",
    fallback_source: str = "coinbase",
    timeframe: str = "1d",
) -> dict[str, int | list[dict]]:
    """Compute and persist the full feature bundle for every watchlist asset.

    If the watchlist is empty we fall back to a single ``fallback_symbol`` run
    so that this flow remains useful out-of-the-box (e.g. fresh deploy with
    only BTC ingest wired up).
    """
    log = get_run_logger()
    results = await _run_watchlist(timeframe)

    if not results:
        log.info("watchlist empty — falling back to %s", fallback_symbol)
        result = await _run_default(fallback_symbol, fallback_source, timeframe)
        results = [result]

    total_rows = sum(r.rows_written for r in results)
    summary = [
        {
            "symbol": r.symbol,
            "rows_written": r.rows_written,
            "rows_read": r.rows_read,
            "extras_computed": r.extras_computed,
        }
        for r in results
    ]
    log.info("compute_features_daily: %d total rows", total_rows)
    return {"rows_written": total_rows, "per_asset": summary}


if __name__ == "__main__":
    asyncio.run(compute_features_daily())
