"""Daily Stage-4 signals flow (06:45 IST).

For each watchlist asset, train + predict + persist a ``Signal`` row. Uses the
runner in :mod:`pfip.signals.runner` which:
  * loads OHLCV
  * computes features
  * looks up the current regime
  * picks the regime specialist (LightGBM baseline + tuning)
  * walk-forward trains with embargo
  * calibrates probabilities (isotonic) on WF holdouts
  * applies the confidence floor (HOLD when below)
  * persists a ``Signal`` to the ``signals`` table

Run manually:

    python -m pfip.prefect.flows.signals_generate_daily
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task

from pfip.core.config import get_settings
from pfip.db.session import get_sessionmaker
from pfip.signals.runner import SignalRunResult, run_for_symbol, run_for_watchlist


@task(name="signals-watchlist")
async def _run_watchlist(timeframe: str) -> list[SignalRunResult]:
    factory = get_sessionmaker()
    async with factory() as session:
        return await run_for_watchlist(session, timeframe=timeframe)


@task(name="signals-default")
async def _run_default(symbol: str, source: str, timeframe: str) -> SignalRunResult:
    factory = get_sessionmaker()
    async with factory() as session:
        return await run_for_symbol(session, symbol=symbol, source=source, timeframe=timeframe)


@flow(name="signals-generate-daily", log_prints=True)
async def signals_generate_daily(
    *,
    fallback_symbol: str = "BTC/USD",
    fallback_source: str = "coinbase",
    timeframe: str = "1d",
) -> dict[str, list[dict] | int]:
    """Produce one signal per watchlist asset and persist."""
    log = get_run_logger()

    # Runtime kill-switch, independent of the deployment's stage gating.
    # ML signals stay OFF until the operator has enough OHLCV history for the
    # walk-forward trainer to be trustworthy, then sets FEATURE_ML_SIGNALS=true.
    if not get_settings().feature_ml_signals:
        log.warning(
            "signals_generate_daily skipped: FEATURE_ML_SIGNALS is off. "
            "Set FEATURE_ML_SIGNALS=true once you have sufficient price history."
        )
        return {"n": 0, "per_asset": [], "skipped": "feature_ml_signals_disabled"}

    results = await _run_watchlist(timeframe)
    if not results:
        log.info("watchlist empty — falling back to %s", fallback_symbol)
        result = await _run_default(fallback_symbol, fallback_source, timeframe)
        results = [result]

    summary = [
        {
            "symbol": r.symbol,
            "direction": r.direction.value,
            "confidence": r.confidence,
            "regime": r.regime.value,
            "status": r.status,
        }
        for r in results
    ]
    log.info("signals_generate_daily: %d signals", len(summary))
    return {"n": len(summary), "per_asset": summary}


if __name__ == "__main__":
    asyncio.run(signals_generate_daily())
