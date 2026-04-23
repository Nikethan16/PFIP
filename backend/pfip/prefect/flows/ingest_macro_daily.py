"""Prefect flow: macro daily ingest.

Schedule: 08:00 UTC.
Pulls FRED core series, DBnomics fallback, World Bank WDI (runs weekly but
idempotent so re-running costs little).
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.macro.dbnomics import ingest_dbnomics
from pfip.ingest.macro.fred import ingest_fred_macro
from pfip.ingest.macro.world_bank import ingest_world_bank


@task(name="fred-macro", retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _fred() -> int:
    return await ingest_fred_macro()


@task(name="dbnomics", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _db() -> int:
    return await ingest_dbnomics()


@task(name="world-bank", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=30))
async def _wb() -> int:
    return await ingest_world_bank()


@flow(name="ingest-macro-daily", log_prints=True)
async def ingest_macro_daily() -> int:
    log = get_run_logger()
    n1 = await _fred()
    n2 = await _db()
    n3 = await _wb()
    total = int(n1) + int(n2) + int(n3)
    log.info(f"ingest-macro-daily total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_macro_daily())
