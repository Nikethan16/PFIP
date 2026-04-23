"""Prefect flow: US daily EOD ingest.

Schedule (wired in Prefect deployments): 22:00 UTC weekdays — ~17:00 EST,
after the US close.

Pulls yfinance for a default watchlist plus stooq as fallback, Tiingo when a
key is set, and SEC EDGAR filings.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.us_equities.sec_edgar import ingest_sec_edgar
from pfip.ingest.us_equities.stooq_ohlcv import ingest_stooq
from pfip.ingest.us_equities.tiingo_ohlcv import ingest_tiingo
from pfip.ingest.us_equities.yfinance_ohlcv import ingest_yfinance


@task(name="yfinance", retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _yf(symbols: list[str]) -> int:
    return await ingest_yfinance(symbols=symbols)


@task(name="stooq-fallback", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _stooq(symbols: list[str]) -> int:
    return await ingest_stooq(symbols=symbols)


@task(name="tiingo", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _tiingo(symbols: list[str]) -> int:
    return await ingest_tiingo(symbols=symbols)


@task(name="sec-edgar", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=15))
async def _sec(ciks: list[int]) -> int:
    return await ingest_sec_edgar(ciks=ciks)


@flow(name="ingest-us-daily", log_prints=True)
async def ingest_us_daily(
    symbols: Iterable[str] = ("SPY", "QQQ", "DIA", "VTI", "AAPL", "MSFT", "GOOGL", "NVDA"),
    ciks: Iterable[int] = (320193, 789019, 1652044, 1045810),  # AAPL, MSFT, GOOGL, NVDA
) -> int:
    log = get_run_logger()
    syms = list(symbols)
    n_yf = await _yf(syms)
    n_stooq = await _stooq(syms)
    n_tiingo = await _tiingo(syms)
    n_sec = await _sec(list(ciks))
    total = int(n_yf) + int(n_stooq) + int(n_tiingo) + int(n_sec)
    log.info(f"ingest-us-daily total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_us_daily())
