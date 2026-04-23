"""EIA US energy data (v2 API).

https://api.eia.gov/v2/seriesid/{series}?api_key=...

We fetch a curated list of energy series (crude oil stocks, natural gas
storage, retail gasoline). Stored in fundamentals.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.commodities.eia")

BASE = "https://api.eia.gov/v2/seriesid"

DEFAULT_SERIES: tuple[str, ...] = (
    "PET.WCESTUS1.W",   # Weekly US crude oil ending stocks
    "NG.NW2_EPG0_SWO_R48_BCF.W",  # NG storage (48 states)
    "PET.EMM_EPMR_PTE_NUS_DPG.W",  # US retail regular gasoline
)


@retry_http(max_attempts=3)
async def _fetch(series_id: str, api_key: str) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}/{series_id}", params={"api_key": api_key})
        r.raise_for_status()
        return r.json()


async def fetch_eia(series: Iterable[str] = DEFAULT_SERIES) -> list[dict[str, Any]]:
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        log.warning("EIA_API_KEY not set, eia no-op")
        return []
    today = date.today()
    rows: list[dict[str, Any]] = []
    for sid in series:
        try:
            resp = await _fetch(sid, key)
        except Exception as e:  # noqa: BLE001
            log.warning(f"eia: {sid} failed: {type(e).__name__}: {e}")
            continue
        data = (resp.get("response") or {}).get("data") or []
        for row in data:
            val = row.get("value")
            p = row.get("period")
            if val is None or not p:
                continue
            try:
                d = date.fromisoformat(str(p)[:10]) if "-" in str(p) else date(int(str(p)[:4]), 12, 31)
                v = float(val)
            except Exception:
                continue
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": d,
                    "symbol": sid,
                    "field": "value",
                    "value": v,
                    "source": "eia",
                }
            )
    return rows


async def ingest_eia(
    series: Iterable[str] = DEFAULT_SERIES, session: AsyncSession | None = None
) -> int:
    log.info("ingest.eia starting")
    rows = await fetch_eia(series)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.eia done: {n} rows")
    return n
