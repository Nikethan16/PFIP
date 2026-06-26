"""Weekly maintenance pass — fundamentals + diligence refresh + (cheap) training.

Runs once a week from the ``weekly`` GitHub Actions workflow. Lower-cadence than
the daily pipeline: refreshes slow-moving fundamentals and the "due diligence"
sources (SEC EDGAR filings, Screener.in ratios, NSE FII/DII, corporate
announcements, SEBI PIT disclosures), then optionally trains the per-regime
LightGBM models if there's enough history for it to be cheap and meaningful.

No Prefect, no Docker — calls the same underlying adapter functions the Prefect
flows wrap, driven directly with asyncio. Every step is non-fatal and time-
bounded so one WAF-blocked NSE endpoint can't sink the run.

Run:

    python -m scripts.run_weekly                 # fundamentals + diligence + training
    python -m scripts.run_weekly --skip-training # skip the LightGBM pass
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from pfip.core.logging import get_logger
from scripts.run_daily_pipeline import (
    StageSummary,
    _guarded,
    _india_watchlist_symbols,
    _us_watchlist_symbols,
)

log = get_logger("scripts.run_weekly")

# SEC CIKs for the US diligence universe (issuers only; ETFs excluded). Mirrors
# pfip.prefect.flows.ingest_due_diligence.US_DILIGENCE_CIKS.
US_DILIGENCE_CIKS: tuple[int, ...] = (
    1045810,  # NVDA
    320193,  # AAPL
    789019,  # MSFT
    1652044,  # GOOGL (Alphabet)
    1318605,  # TSLA
    1326801,  # META
    1018724,  # AMZN
)

# Crypto symbol with the deepest history — the natural slot to train the
# per-regime LightGBM models on (BTC has full 3y coverage).
TRAIN_SYMBOL = "BTC/USD"


async def stage_fundamentals_and_diligence() -> StageSummary:
    """Refresh fundamentals + all dormant diligence adapters. Each non-fatal."""
    summary = StageSummary(name="fundamentals_diligence")

    async def _sec() -> int:
        from pfip.ingest.us_equities.sec_edgar import ingest_sec_edgar

        return await ingest_sec_edgar(ciks=list(US_DILIGENCE_CIKS))

    await _guarded(summary, "sec_edgar", _sec, timeout=300.0)

    async def _finnhub() -> int:
        from pfip.ingest.us_equities.finnhub_fundamentals import ingest_finnhub

        return await ingest_finnhub(symbols=await _us_watchlist_symbols())

    await _guarded(summary, "finnhub", _finnhub, timeout=180.0)

    async def _screener() -> int:
        from pfip.ingest.indian_equities.screener_fundamentals import ingest_screener

        return await ingest_screener(symbols=await _india_watchlist_symbols())

    await _guarded(summary, "screener", _screener, timeout=420.0)

    async def _fii_dii() -> int:
        from pfip.ingest.indian_equities.nse_fii_dii import ingest_fii_dii

        return await ingest_fii_dii()

    await _guarded(summary, "nse_fii_dii", _fii_dii, timeout=120.0)

    async def _corp() -> int:
        from pfip.ingest.indian_equities.nse_corporate_announcements import (
            ingest_nse_corporate_announcements,
        )

        return await ingest_nse_corporate_announcements()

    await _guarded(summary, "nse_corp_announcements", _corp, timeout=120.0)

    async def _pit() -> int:
        from pfip.ingest.indian_equities.nse_pit_disclosures import ingest_nse_pit

        return await ingest_nse_pit()

    await _guarded(summary, "nse_pit_disclosures", _pit, timeout=120.0)

    async def _nasdaq() -> int:
        from pfip.ingest.commodities.nasdaq_data_link import ingest_nasdaq_data_link

        return await ingest_nasdaq_data_link()

    await _guarded(summary, "nasdaq_data_link", _nasdaq, timeout=120.0)

    summary.finish()
    return summary


async def stage_training(*, symbol: str = TRAIN_SYMBOL) -> StageSummary:
    """Retrain per-regime LightGBM champions across the watchlist.

    Uses ``pfip.signals.retrain.retrain_universe`` — a plain-async retrainer that
    pools data across the universe per regime, OOS-gates, and promotes a new
    champion only if it beats the incumbent. Replaces the old Prefect flow, which
    no longer runs (Prefect 2.20 is incompatible with the upgraded anyio).
    Non-fatal: thin data / missing LightGBM just yields an empty result.
    """
    summary = StageSummary(name="training")

    async def _train() -> dict[str, Any]:
        from pfip.db.session import get_sessionmaker
        from pfip.signals.retrain import retrain_universe

        factory = get_sessionmaker()
        async with factory() as s:
            return await retrain_universe(s)

    await _guarded(summary, "retrain_universe", _train, timeout=1800.0)
    summary.finish()
    return summary


async def run_weekly(*, training: bool = True) -> dict[str, Any]:
    log.info(f"weekly maintenance starting: training={training}")
    started = time.monotonic()
    results: dict[str, Any] = {}

    fd = await stage_fundamentals_and_diligence()
    results["fundamentals_diligence"] = fd.as_dict()

    if training:
        tr = await stage_training()
        results["training"] = tr.as_dict()

    summary = {
        "training": training,
        "elapsed_s": round(time.monotonic() - started, 1),
        "results": results,
    }
    log.info("weekly summary:\n" + json.dumps(summary, indent=2, default=str))
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Weekly fundamentals/diligence refresh + optional LightGBM training.",
    )
    p.add_argument(
        "--skip-training",
        action="store_true",
        help="Skip the per-regime LightGBM training pass.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    return asyncio.run(run_weekly(training=not args.skip_training))


if __name__ == "__main__":
    main()
