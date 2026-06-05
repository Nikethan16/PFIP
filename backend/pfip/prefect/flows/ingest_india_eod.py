"""Prefect flow: Indian equities EOD ingest.

Cadence: daily 16:30 IST = 11:00 UTC (after NSE/BSE close).

Pulls jugaad-data NSE EOD, NSE+BSE bhavcopy, FII/DII flows, NSE F&O bhavcopy,
NSE PIT disclosures, NSE corporate announcements. Reads watchlist for the
per-symbol parts.

Manual run:
    python -m pfip.prefect.flows.ingest_india_eod
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff
from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.ingest._common.source_health import record_run
from pfip.ingest.indian_equities.bse_bhavcopy import ingest_bse_bhavcopy
from pfip.ingest.indian_equities.jugaad_ohlcv import ingest_jugaad
from pfip.ingest.indian_equities.nse_bhavcopy import ingest_nse_bhavcopy
from pfip.ingest.indian_equities.nse_corporate_announcements import (
    ingest_nse_corporate_announcements,
)
from pfip.ingest.indian_equities.nse_fii_dii import ingest_fii_dii
from pfip.ingest.indian_equities.nse_fno_bhavcopy import ingest_fno_bhavcopy
from pfip.ingest.indian_equities.nse_pit_disclosures import ingest_nse_pit

FALLBACK_IN_SYMBOLS = ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC")


async def _watchlist_in_symbols() -> list[str]:
    factory = get_sessionmaker()
    try:
        async with factory() as s:
            r = await s.execute(
                text(
                    """
                    SELECT symbol FROM watchlist
                    WHERE upper(market) IN ('IN', 'NSE', 'BSE', 'NIFTY50', 'NIFTY500', 'SENSEX')
                       OR symbol ~ '\\.(NS|BO)$'
                    """
                )
            )
            syms = [row[0].replace(".NS", "").replace(".BO", "") for row in r.fetchall() if row and row[0]]
            return syms or list(FALLBACK_IN_SYMBOLS)
    except Exception:
        return list(FALLBACK_IN_SYMBOLS)


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


_jugaad = _make_task("jugaad", ingest_jugaad)
_nse_bhav = _make_task("nse_bhavcopy", ingest_nse_bhavcopy)
_bse_bhav = _make_task("bse_bhavcopy", ingest_bse_bhavcopy)
_fii_dii = _make_task("fii_dii", ingest_fii_dii)
_fno = _make_task("nse_fno_bhavcopy", ingest_fno_bhavcopy)
_pit = _make_task("nse_pit_disclosures", ingest_nse_pit)
_corp_ann = _make_task("nse_corp_announcements", ingest_nse_corporate_announcements)


@flow(name="ingest-india-eod", log_prints=True)
async def ingest_india_eod(symbols: Iterable[str] | None = None) -> int:
    log = get_run_logger()
    syms = list(symbols) if symbols is not None else await _watchlist_in_symbols()
    log.info(f"ingest-india-eod symbols: {len(syms)} ({syms[:5]}{'…' if len(syms) > 5 else ''})")
    results = await asyncio.gather(
        _jugaad(symbols=syms),
        _nse_bhav(),
        _bse_bhav(),
        _fii_dii(),
        _fno(),
        _pit(),
        _corp_ann(),
        return_exceptions=True,
    )
    total = 0
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"task failed: {type(r).__name__}: {r}")
            continue
        total += int(r)
    log.info(f"ingest-india-eod total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_india_eod())
