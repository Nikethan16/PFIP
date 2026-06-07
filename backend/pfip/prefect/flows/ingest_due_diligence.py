"""Prefect flows: dedicated "due diligence" data adapters.

These thin flow wrappers expose each dormant due-diligence adapter as its own
schedulable Prefect deployment, so a failure in one source (e.g. an NSE WAF
block) does not mask the others and each gets independent run history.

The same adapters also run bundled inside ``ingest_india_eod`` /
``ingest_fundamentals_weekly`` / ``ingest_us_eod``; these standalone flows are
the per-source, per-cadence variants registered by ``schedules.prefect_deployments``:

- sec_edgar_filings        weekly   (US 10-K/10-Q/8-K + companyfacts)
- screener_fundamentals    weekly   (India NIFTY-50 .NS ratios)
- nse_fii_dii              daily    (market-level FII/DII flows)
- nse_corp_announcements   daily    (India corporate announcements)
- nse_pit_disclosures      daily    (India insider / SEBI PIT disclosures)

Manual run example:
    python -m pfip.prefect.flows.ingest_due_diligence
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger
from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.ingest._common.source_health import record_run
from pfip.ingest.indian_equities.nse_corporate_announcements import (
    ingest_nse_corporate_announcements,
)
from pfip.ingest.indian_equities.nse_fii_dii import ingest_fii_dii
from pfip.ingest.indian_equities.nse_pit_disclosures import ingest_nse_pit
from pfip.ingest.indian_equities.screener_fundamentals import ingest_screener
from pfip.ingest.us_equities.sec_edgar import ingest_sec_edgar

# US watchlist tickers (NVDA AAPL MSFT GOOGL TSLA META AMZN) -> SEC CIKs.
# ETFs (SPY/QQQ/VTI) are intentionally excluded — SEC EDGAR is for issuers.
US_DILIGENCE_CIKS: tuple[int, ...] = (
    1045810,  # NVDA
    320193,  # AAPL
    789019,  # MSFT
    1652044,  # GOOGL (Alphabet)
    1318605,  # TSLA
    1326801,  # META
    1018724,  # AMZN
)

FALLBACK_IN_SYMBOLS = ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC")


async def _watchlist_in_symbols() -> list[str]:
    """Return NIFTY-50 / India symbols (``.NS`` stripped) from the watchlist."""
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
            syms = [
                row[0].replace(".NS", "").replace(".BO", "")
                for row in r.fetchall()
                if row and row[0]
            ]
            return syms or list(FALLBACK_IN_SYMBOLS)
    except Exception:  # noqa: BLE001
        return list(FALLBACK_IN_SYMBOLS)


@flow(name="ingest-sec-edgar-filings", log_prints=True)
async def ingest_sec_edgar_filings(ciks: Iterable[int] = US_DILIGENCE_CIKS) -> int:
    """US SEC filings (10-K/10-Q/8-K) + companyfacts for the US watchlist."""
    log = get_run_logger()
    n = 0
    err = None
    try:
        n = await ingest_sec_edgar(ciks=list(ciks))
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning(f"sec_edgar_filings failed: {err}")
    finally:
        await record_run("sec_edgar_filings", rows=n, error=err)
    log.info(f"ingest-sec-edgar-filings rows: {n}")
    return n


@flow(name="ingest-screener-fundamentals", log_prints=True)
async def ingest_screener_fundamentals(symbols: Iterable[str] | None = None) -> int:
    """India fundamentals (Screener.in) for the NIFTY-50 .NS universe."""
    log = get_run_logger()
    syms = list(symbols) if symbols is not None else await _watchlist_in_symbols()
    log.info(f"screener: {len(syms)} symbols")
    n = 0
    err = None
    try:
        n = await ingest_screener(symbols=syms)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning(f"screener_fundamentals failed: {err}")
    finally:
        await record_run("screener_fundamentals", rows=n, error=err)
    log.info(f"ingest-screener-fundamentals rows: {n}")
    return n


@flow(name="ingest-nse-fii-dii", log_prints=True)
async def ingest_nse_fii_dii() -> int:
    """Market-level FII/DII institutional flows (NSE)."""
    log = get_run_logger()
    n = 0
    err = None
    try:
        n = await ingest_fii_dii()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning(f"nse_fii_dii failed: {err}")
    finally:
        await record_run("nse_fii_dii", rows=n, error=err)
    log.info(f"ingest-nse-fii-dii rows: {n}")
    return n


@flow(name="ingest-nse-corp-announcements", log_prints=True)
async def ingest_nse_corp_announcements() -> int:
    """India corporate announcements (NSE)."""
    log = get_run_logger()
    n = 0
    err = None
    try:
        n = await ingest_nse_corporate_announcements()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning(f"nse_corp_announcements failed: {err}")
    finally:
        await record_run("nse_corp_announcements", rows=n, error=err)
    log.info(f"ingest-nse-corp-announcements rows: {n}")
    return n


@flow(name="ingest-nse-pit-disclosures", log_prints=True)
async def ingest_nse_pit_disclosures() -> int:
    """India insider / SEBI PIT disclosures (NSE)."""
    log = get_run_logger()
    n = 0
    err = None
    try:
        n = await ingest_nse_pit()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning(f"nse_pit_disclosures failed: {err}")
    finally:
        await record_run("nse_pit_disclosures", rows=n, error=err)
    log.info(f"ingest-nse-pit-disclosures rows: {n}")
    return n


if __name__ == "__main__":

    async def _all() -> None:
        for f in (
            ingest_sec_edgar_filings,
            ingest_screener_fundamentals,
            ingest_nse_fii_dii,
            ingest_nse_corp_announcements,
            ingest_nse_pit_disclosures,
        ):
            await f()

    asyncio.run(_all())
