"""NSE daily FII/DII flows.

Endpoint: ``https://www.nseindia.com/api/fiidiiTradeReact``
Stored as fundamentals rows with symbol=``FII_FLOW`` / ``DII_FLOW`` and
field = buy/sell/net per category.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.indian_equities.nse_fii_dii")

URL = "https://www.nseindia.com/api/fiidiiTradeReact"
HOME = "https://www.nseindia.com/"


@retry_http(max_attempts=3)
async def _fetch() -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/reports/fii-dii",
    }
    async with get_async_client(headers=headers) as client:
        await client.get(HOME)
        await asyncio.sleep(2)
        r = await client.get(URL)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []


async def fetch_fii_dii() -> list[dict[str, Any]]:
    try:
        raw = await _fetch()
    except Exception as e:  # noqa: BLE001
        log.warning(f"nse_fii_dii: failed: {type(e).__name__}: {e}")
        return []
    today = date.today()
    rows: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        cat = (r.get("category") or "").upper().replace(" ", "_")
        if not cat:
            continue
        d_str = r.get("date") or None
        try:
            d = (
                datetime.strptime(d_str, "%d-%b-%Y").date()
                if d_str
                else today
            )
        except Exception:
            d = today
        sym = f"{cat}_FLOW"
        for field in ("buyValue", "sellValue", "netValue"):
            val = r.get(field)
            if val is None:
                continue
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": d,
                    "symbol": sym,
                    "field": field,
                    "value": val,
                    "source": "nse_fii_dii",
                }
            )
    return rows


async def ingest_fii_dii(session: AsyncSession | None = None) -> int:
    log.info("ingest.nse_fii_dii starting")
    rows = await fetch_fii_dii()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.nse_fii_dii done: {n} rows")
    return n
