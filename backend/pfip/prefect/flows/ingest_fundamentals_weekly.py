"""Prefect flow: weekly fundamentals refresh.

Cadence: Saturday 04:00 IST = Friday 22:30 UTC.

Sources:
- SEC EDGAR submissions + companyfacts (US watchlist)
- Screener.in fundamentals (India watchlist)
- Finnhub /stock/metric (US watchlist supplement)
- NASDAQ Data Link curated datasets

Manual run:
    python -m pfip.prefect.flows.ingest_fundamentals_weekly
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff
from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.ingest._common.source_health import record_run
from pfip.ingest.commodities.nasdaq_data_link import ingest_nasdaq_data_link
from pfip.ingest.indian_equities.screener_fundamentals import ingest_screener
from pfip.ingest.us_equities.finnhub_fundamentals import ingest_finnhub_metrics
from pfip.ingest.us_equities.sec_edgar import ingest_sec_edgar

# Default CIKs — overridden when watchlist contains US tickers.
DEFAULT_CIKS = (320193, 789019, 1652044, 1045810, 1326801, 1318605)


async def _watchlist_split() -> tuple[list[str], list[str]]:
    """Return (us_symbols, in_symbols) from the watchlist."""
    factory = get_sessionmaker()
    us: list[str] = []
    inn: list[str] = []
    try:
        async with factory() as s:
            r = await s.execute(text("SELECT symbol, market FROM watchlist"))
            for sym, mkt in r.fetchall():
                m = (mkt or "").upper()
                if m in ("IN", "NSE", "BSE", "NIFTY50", "NIFTY500", "SENSEX") or sym.endswith((".NS", ".BO")):
                    inn.append(sym.replace(".NS", "").replace(".BO", ""))
                else:
                    us.append(sym)
    except Exception:
        pass
    return us, inn


def _make_task(name: str, fn):  # type: ignore[no-untyped-def]
    @task(name=name, retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=15))
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


_sec = _make_task("sec_edgar_weekly", ingest_sec_edgar)
_screener = _make_task("screener_weekly", ingest_screener)
_finnhub = _make_task("finnhub_weekly", ingest_finnhub_metrics)
_ndl = _make_task("nasdaq_data_link", ingest_nasdaq_data_link)


@flow(name="ingest-fundamentals-weekly", log_prints=True)
async def ingest_fundamentals_weekly(
    us_symbols: Iterable[str] | None = None,
    in_symbols: Iterable[str] | None = None,
    ciks: Iterable[int] = DEFAULT_CIKS,
) -> int:
    log = get_run_logger()
    if us_symbols is None or in_symbols is None:
        wl_us, wl_in = await _watchlist_split()
        if us_symbols is None:
            us_symbols = wl_us
        if in_symbols is None:
            in_symbols = wl_in
    us_list = list(us_symbols)
    in_list = list(in_symbols)
    log.info(f"fundamentals: us={len(us_list)} in={len(in_list)}")

    results = await asyncio.gather(
        _sec(ciks=list(ciks)),
        _screener(symbols=in_list) if in_list else asyncio.sleep(0, result=0),
        _finnhub(symbols=us_list) if us_list else asyncio.sleep(0, result=0),
        _ndl(),
        return_exceptions=True,
    )
    total = 0
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"task failed: {type(r).__name__}: {r}")
            continue
        total += int(r or 0)
    log.info(f"ingest-fundamentals-weekly total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_fundamentals_weekly())
