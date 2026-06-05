"""Prefect flow: Indian mutual fund NAV daily ingest.

Cadence: daily 22:00 IST = 16:30 UTC (after AMFI publishes evening NAVs).

Manual run:
    python -m pfip.prefect.flows.ingest_mf_daily
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest._common.source_health import record_run
from pfip.ingest.indian_mf.amfi_nav import ingest_amfi_nav


@task(name="amfi-nav", retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=15))
async def _amfi() -> int:
    n = 0
    err = None
    try:
        n = await ingest_amfi_nav()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("amfi_nav", rows=n, error=err)
    return n


@flow(name="ingest-mf-daily", log_prints=True)
async def ingest_mf_daily() -> int:
    log = get_run_logger()
    n = await _amfi()
    log.info(f"ingest-mf-daily total rows: {n}")
    return n


if __name__ == "__main__":
    asyncio.run(ingest_mf_daily())
