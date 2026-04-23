"""Prefect flow: FX daily ingest.

Schedule: 18:00 UTC — after ECB fix.
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.fx.fred_fx import ingest_fred_fx
from pfip.ingest.fx.frankfurter import ingest_frankfurter
from pfip.ingest.fx.rbi_reference import ingest_rbi_reference


@task(name="frankfurter", retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _frank() -> int:
    return await ingest_frankfurter()


@task(name="rbi", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _rbi() -> int:
    return await ingest_rbi_reference()


@task(name="fred-fx", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _fred_fx() -> int:
    return await ingest_fred_fx()


@flow(name="ingest-fx-daily", log_prints=True)
async def ingest_fx_daily() -> int:
    log = get_run_logger()
    n1 = await _frank()
    n2 = await _rbi()
    n3 = await _fred_fx()
    total = int(n1) + int(n2) + int(n3)
    log.info(f"ingest-fx-daily total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_fx_daily())
