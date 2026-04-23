"""LBMA gold (and silver) daily fix.

LBMA publishes the fix at https://prices.lbma.org.uk/json/gold_pm.json (and
``gold_am.json``, ``silver.json``). These JSON endpoints are publicly
accessible and return dated entries of the form: ``[["YYYY-MM-DD", [usd, gbp, eur]]]``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.commodities.lbma_gold")

ENDPOINTS: dict[str, str] = {
    "XAUUSD_AM": "https://prices.lbma.org.uk/json/gold_am.json",
    "XAUUSD_PM": "https://prices.lbma.org.uk/json/gold_pm.json",
    "XAGUSD": "https://prices.lbma.org.uk/json/silver.json",
}


@retry_http(max_attempts=3)
async def _fetch(url: str) -> list[Any]:
    async with get_async_client() as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []


async def fetch_lbma() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym, url in ENDPOINTS.items():
        try:
            data = await _fetch(url)
        except Exception as e:  # noqa: BLE001
            log.warning(f"lbma: {sym} failed: {type(e).__name__}: {e}")
            continue
        for entry in data:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            d_str = entry[0]
            vals = entry[1]
            if not isinstance(vals, list) or not vals:
                continue
            usd = vals[0]
            try:
                t = datetime.fromisoformat(d_str).replace(tzinfo=timezone.utc)
                v = float(usd)
            except Exception:
                continue
            rows.append(
                {
                    "time": t,
                    "symbol": sym,
                    "market": "COMMODITY",
                    "source": "lbma",
                    "timeframe": "1d",
                    "open": v,
                    "high": v,
                    "low": v,
                    "close": v,
                    "volume": 0,
                }
            )
    return rows


async def ingest_lbma_gold(session: AsyncSession | None = None) -> int:
    log.info("ingest.lbma_gold starting")
    rows = await fetch_lbma()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.lbma_gold done: {n} rows")
    return n
