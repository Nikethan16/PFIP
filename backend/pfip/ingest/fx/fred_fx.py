"""FRED FX series — DEXINUS (India/US), DEXUSEU (EUR/USD), DEXJPUS, DEXUSUK.

Stores OHLCV rows with open=high=low=close=rate.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.fx.fred_fx")

BASE = "https://api.stlouisfed.org/fred/series/observations"

_SERIES_MAP: dict[str, str] = {
    "DEXINUS": "USDINR",
    "DEXUSEU": "EURUSD",
    "DEXUSUK": "GBPUSD",
    "DEXJPUS": "USDJPY",
}


@retry_http(max_attempts=3)
async def _fetch_series(series_id: str, api_key: str) -> list[dict[str, Any]]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": "2018-01-01",
    }
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return (r.json() or {}).get("observations") or []


async def fetch_fred_fx(series_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        log.warning("FRED_API_KEY not set, fred_fx no-op")
        return []
    series = list(series_ids or _SERIES_MAP.keys())
    rows: list[dict[str, Any]] = []
    for sid in series:
        sym = _SERIES_MAP.get(sid, sid)
        try:
            obs = await _fetch_series(sid, key)
        except Exception as e:  # noqa: BLE001
            log.warning(f"fred_fx: {sid} failed: {type(e).__name__}: {e}")
            continue
        for o in obs:
            val = o.get("value")
            if val in (None, "", "."):
                continue
            try:
                v = float(val)
                t = datetime.fromisoformat(o["date"]).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            rows.append(
                {
                    "time": t,
                    "symbol": sym,
                    "market": "FX",
                    "source": "fred",
                    "timeframe": "1d",
                    "open": v,
                    "high": v,
                    "low": v,
                    "close": v,
                    "volume": 0,
                }
            )
    return rows


async def ingest_fred_fx(
    series_ids: Iterable[str] | None = None, session: AsyncSession | None = None
) -> int:
    log.info("ingest.fred_fx starting")
    rows = await fetch_fred_fx(series_ids)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.fred_fx done: {n} rows")
    return n
