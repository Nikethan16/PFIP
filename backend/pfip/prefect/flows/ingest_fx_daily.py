"""Prefect flow: daily FX reference-rate ingest into ``fx_rates``.

Populates the dedicated ``fx_rates`` table (migration 0006) used by the
USD->INR mark-to-market / tax-conversion path in
:mod:`pfip.tax.fx_cost_basis`.

Cadence: once daily at 18:00 UTC (after the ECB reference fix). Each run pulls
the latest USD/EUR/GBP -> INR rate. On the first run (or any run with
``backfill=True``) it also backfills the trailing ``backfill_days`` so a fresh
DB has history for back-dated tax lots.

Manual run (latest only):
    python -m pfip.prefect.flows.ingest_fx_daily

Manual backfill (e.g. ~2 years) from a REPL / one-off:
    python -c "import asyncio; from pfip.prefect.flows.ingest_fx_daily import ingest_fx_daily; \
asyncio.run(ingest_fx_daily(backfill=True, backfill_days=730))"
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest._common.source_health import record_run
from pfip.ingest.macro.fx_rates import ingest_fx_rates


@task(name="fx-rates-latest", retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _latest() -> int:
    n = 0
    err: str | None = None
    try:
        n = await ingest_fx_rates(mode="latest")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("fx_rates", rows=n, error=err)
    return n


@task(name="fx-rates-backfill", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _backfill(days: int) -> int:
    n = 0
    err: str | None = None
    try:
        n = await ingest_fx_rates(mode="backfill", lookback_days=days)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("fx_rates_backfill", rows=n, error=err)
    return n


@flow(name="ingest-fx-daily", log_prints=True)
async def ingest_fx_daily(*, backfill: bool = False, backfill_days: int = 365) -> int:
    """Daily FX ingest into ``fx_rates``.

    Always pulls the latest rate. When ``backfill=True`` (first run / manual)
    it additionally backfills the trailing ``backfill_days`` of history.
    """
    log = get_run_logger()
    total = 0
    if backfill:
        n_back = await _backfill(backfill_days)
        total += int(n_back)
        log.info(f"ingest-fx-daily backfill rows: {n_back} ({backfill_days}d)")
    n_latest = await _latest()
    total += int(n_latest)
    log.info(f"ingest-fx-daily total rows: {total} (latest={n_latest})")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_fx_daily())
