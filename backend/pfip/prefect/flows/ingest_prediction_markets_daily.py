"""Prefect flow: prediction markets daily."""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.prediction_markets.kalshi import ingest_kalshi
from pfip.ingest.prediction_markets.polymarket import ingest_polymarket


@task(name="polymarket", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _poly() -> int:
    return await ingest_polymarket()


@task(name="kalshi", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _kalshi() -> int:
    return await ingest_kalshi()


@flow(name="ingest-prediction-markets-daily", log_prints=True)
async def ingest_prediction_markets_daily() -> int:
    log = get_run_logger()
    n1 = await _poly()
    n2 = await _kalshi()
    total = int(n1) + int(n2)
    log.info(f"ingest-prediction-markets-daily rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_prediction_markets_daily())
