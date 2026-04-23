"""Prefect flow: Indian daily ingest.

Schedule: 11:00 UTC weekdays (~16:30 IST — after NSE close).

Pulls NSE EOD via jugaad + bhavcopy, BSE bhavcopy, AMFI NAV, FII/DII flows,
Screener fundamentals for watchlist, and PIT disclosures from NSE.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.indian_equities.bse_bhavcopy import ingest_bse_bhavcopy
from pfip.ingest.indian_equities.jugaad_ohlcv import ingest_jugaad
from pfip.ingest.indian_equities.nse_bhavcopy import ingest_nse_bhavcopy
from pfip.ingest.indian_equities.nse_fii_dii import ingest_fii_dii
from pfip.ingest.indian_equities.nse_fno_bhavcopy import ingest_fno_bhavcopy
from pfip.ingest.indian_equities.nse_pit_disclosures import ingest_nse_pit
from pfip.ingest.indian_equities.screener_fundamentals import ingest_screener
from pfip.ingest.indian_mf.amfi_nav import ingest_amfi_nav


@task(name="jugaad-nse", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _jugaad(symbols: list[str]) -> int:
    return await ingest_jugaad(symbols=symbols)


@task(name="nse-bhavcopy", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _nse_bhav() -> int:
    return await ingest_nse_bhavcopy()


@task(name="bse-bhavcopy", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _bse_bhav() -> int:
    return await ingest_bse_bhavcopy()


@task(name="amfi-nav", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _amfi() -> int:
    return await ingest_amfi_nav()


@task(name="fii-dii", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _fii_dii() -> int:
    return await ingest_fii_dii()


@task(name="nse-fno", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _fno() -> int:
    return await ingest_fno_bhavcopy()


@task(name="screener", retries=1, retry_delay_seconds=30)
async def _screener(symbols: list[str]) -> int:
    return await ingest_screener(symbols=symbols)


@task(name="pit-disclosures", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _pit() -> int:
    return await ingest_nse_pit()


@flow(name="ingest-indian-daily", log_prints=True)
async def ingest_indian_daily(
    symbols: Iterable[str] = ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"),
) -> int:
    log = get_run_logger()
    syms = list(symbols)
    n1 = await _jugaad(syms)
    n2 = await _nse_bhav()
    n3 = await _bse_bhav()
    n4 = await _amfi()
    n5 = await _fii_dii()
    n6 = await _fno()
    n7 = await _screener(syms)
    n8 = await _pit()
    total = sum(int(x) for x in (n1, n2, n3, n4, n5, n6, n7, n8))
    log.info(f"ingest-indian-daily total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_indian_daily())
