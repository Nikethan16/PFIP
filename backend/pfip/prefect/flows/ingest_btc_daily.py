"""Prefect flow: daily BTC/USD OHLCV ingest from Coinbase.

Manual run:
    python -m pfip.prefect.flows.ingest_btc_daily
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.ccxt_ohlcv import ingest_ohlcv


@task(
    name="ingest-ohlcv",
    retries=3,
    retry_delay_seconds=exponential_backoff(backoff_factor=10),
)
async def _ingest_task(
    exchange: str, symbol: str, timeframe: str, since: datetime | None
) -> int:
    log = get_run_logger()
    log.info(f"Starting ingest: {exchange} {symbol} {timeframe} since={since}")
    n = await ingest_ohlcv(exchange=exchange, symbol=symbol, timeframe=timeframe, since=since)
    log.info(f"Ingest done: {n} candles attempted")
    return n


@flow(name="ingest-btc-daily", log_prints=True)
async def ingest_btc_daily(
    exchange: str = "coinbase",
    symbol: str = "BTC/USD",
    timeframe: str = "1d",
    lookback_days: int = 400,
) -> int:
    """Fetch daily BTC candles and upsert them.

    By default we pull the last ``lookback_days`` days so re-runs backfill gaps.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
    return await _ingest_task(exchange, symbol, timeframe, since)


if __name__ == "__main__":
    asyncio.run(ingest_btc_daily())
