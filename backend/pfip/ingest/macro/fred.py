"""FRED macro series — core backbone.

Default series set (can be overridden): CPI, Fed Funds, VIX, DXY, UST yields.
All rows stored in ``fundamentals`` (single scalar per date), with:
    as_of_date = observation date (FRED is PIT-friendly for most series,
    though real PIT would need ALFRED vintages; out of scope here).
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.macro.fred")

BASE = "https://api.stlouisfed.org/fred/series/observations"

DEFAULT_SERIES: tuple[str, ...] = (
    "CPIAUCSL",  # CPI All Urban Consumers
    "CPILFESL",  # Core CPI
    "FEDFUNDS",  # Fed Funds
    "DFF",  # Effective Fed Funds Rate
    "DGS2",  # 2Y UST yield
    "DGS10",  # 10Y UST yield
    "DGS30",  # 30Y UST yield
    "T10Y2Y",  # 10Y-2Y spread
    "VIXCLS",  # VIX close
    "DTWEXBGS",  # USD broad index (DXY proxy)
    "UNRATE",  # Unemployment
    "PAYEMS",  # Nonfarm payrolls
)


# Rolling window (days) of macro history to keep fresh each run. A macro
# backbone only needs the recent path for regime/brief context, and a bounded
# window keeps the nightly upsert light on free-tier Neon (the unbounded
# 2010→today pull was ~48k rows re-attempted every night).
_LOOKBACK_DAYS = 1100  # ~3 years


@retry_http(max_attempts=3)
async def _fetch_series(
    series_id: str, api_key: str, observation_start: str
) -> list[dict[str, Any]]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
    }
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return (r.json() or {}).get("observations") or []


async def fetch_fred_macro(series: Iterable[str] = DEFAULT_SERIES) -> list[dict[str, Any]]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        log.warning("FRED_API_KEY not set, fred macro no-op")
        return []
    observation_start = (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    rows: list[dict[str, Any]] = []
    for sid in series:
        try:
            obs = await _fetch_series(sid, key, observation_start)
        except Exception as e:  # noqa: BLE001
            log.warning(f"fred: {sid} failed: {type(e).__name__}: {e}")
            continue
        for o in obs:
            val = o.get("value")
            if val in (None, "", "."):
                continue
            try:
                v = float(val)
                d = date.fromisoformat(o["date"])
            except Exception:
                continue
            # as_of_date = the OBSERVATION date so each dated point is a distinct
            # row. Stamping today() (the old behaviour) collided every dated
            # observation of a series onto one conflict key → the whole macro
            # series persisted as a single latest value.
            rows.append(
                {
                    "as_of_date": d,
                    "report_date": d,
                    "symbol": sid,
                    "field": "value",
                    "value": v,
                    "source": "fred",
                }
            )
    return rows


async def ingest_fred_macro(
    series: Iterable[str] = DEFAULT_SERIES, session: AsyncSession | None = None
) -> int:
    log.info("ingest.fred_macro starting")
    rows = await fetch_fred_macro(series)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.fred_macro done: {n} rows")
    return n
