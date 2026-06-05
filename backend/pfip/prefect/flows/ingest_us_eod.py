"""Prefect flow: US equities EOD ingest.

Cadence: daily 22:30 IST = 17:00 UTC (after US close).

Reads watchlist from DB (US-market rows). Falls back to a hard-coded default
if the table is empty or unreachable.

Pulls yfinance (primary), Stooq (delisted-aware backup), Tiingo (quality
fallback if a key is set), and SEC EDGAR filings for major holdings.

Manual run:
    python -m pfip.prefect.flows.ingest_us_eod
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff
from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.ingest._common.source_health import record_run
from pfip.ingest.us_equities.finnhub_fundamentals import ingest_finnhub_metrics
from pfip.ingest.us_equities.sec_edgar import ingest_sec_edgar
from pfip.ingest.us_equities.stooq_ohlcv import ingest_stooq
from pfip.ingest.us_equities.tiingo_ohlcv import ingest_tiingo
from pfip.ingest.us_equities.yfinance_ohlcv import ingest_yfinance

FALLBACK_US_SYMBOLS = ("SPY", "QQQ", "DIA", "VTI", "AAPL", "MSFT", "GOOGL", "NVDA", "META", "TSLA")
FALLBACK_CIKS = (320193, 789019, 1652044, 1045810, 1326801, 1318605)  # AAPL/MSFT/GOOGL/NVDA/META/TSLA


async def _watchlist_us_symbols() -> list[str]:
    factory = get_sessionmaker()
    try:
        async with factory() as s:
            r = await s.execute(
                text(
                    """
                    SELECT symbol FROM watchlist
                    WHERE upper(market) IN ('US', 'US_EQUITY', 'US_ETF', 'SPY', 'QQQ', 'DIA', 'VTI')
                       OR symbol ~ '^[A-Z]{1,5}$'
                    """
                )
            )
            syms = [row[0] for row in r.fetchall() if row and row[0]]
            return syms or list(FALLBACK_US_SYMBOLS)
    except Exception:
        return list(FALLBACK_US_SYMBOLS)


def _make_task(name: str, fn):  # type: ignore[no-untyped-def]
    @task(name=name, retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
    async def _t(*args, **kwargs):
        n = 0
        err = None
        try:
            n = await fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            raise
        finally:
            await record_run(name.replace("-", "_"), rows=n, error=err)
        return n

    return _t


_yf = _make_task("yfinance", ingest_yfinance)
_stooq = _make_task("stooq", ingest_stooq)
_tiingo = _make_task("tiingo", ingest_tiingo)
_sec = _make_task("sec_edgar", ingest_sec_edgar)
_finnhub = _make_task("finnhub_metrics", ingest_finnhub_metrics)


@flow(name="ingest-us-eod", log_prints=True)
async def ingest_us_eod(
    symbols: Iterable[str] | None = None,
    ciks: Iterable[int] = FALLBACK_CIKS,
) -> int:
    log = get_run_logger()
    syms = list(symbols) if symbols is not None else await _watchlist_us_symbols()
    log.info(f"ingest-us-eod symbols: {len(syms)} ({syms[:5]}{'…' if len(syms) > 5 else ''})")
    results = await asyncio.gather(
        _yf(symbols=syms),
        _stooq(symbols=syms),
        _tiingo(symbols=syms),
        _sec(ciks=list(ciks)),
        _finnhub(symbols=syms),
        return_exceptions=True,
    )
    total = 0
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"task failed: {type(r).__name__}: {r}")
            continue
        total += int(r)
    log.info(f"ingest-us-eod total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_us_eod())
