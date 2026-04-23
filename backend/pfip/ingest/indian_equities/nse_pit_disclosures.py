"""NSE insider / SEBI PIT disclosures (corporate announcements).

Endpoint: ``https://www.nseindia.com/api/corporate-announcements``
We filter the announcement feed for insider-trading (SEBI PIT) disclosures and
store them as news rows with category=``pit_disclosure``.

NSE blocks bots; we use a browser-y UA and warm-up GET to set cookies.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.indian_equities.nse_pit_disclosures")

ANN_URL = "https://www.nseindia.com/api/corporate-announcements"
HOME_URL = "https://www.nseindia.com/"

_POLITE_DELAY_SEC = 2.0

_PIT_KEYWORDS = ("insider", "pit", "reg. 7", "regulation 7", "sast", "trading window")


@retry_http(max_attempts=3)
async def _fetch() -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    }
    async with get_async_client(headers=headers, follow_redirects=True) as client:
        await client.get(HOME_URL)  # warm up cookies
        await asyncio.sleep(_POLITE_DELAY_SEC)
        r = await client.get(ANN_URL, params={"index": "equities"})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])


async def fetch_pit_disclosures() -> list[dict[str, Any]]:
    try:
        raw = await _fetch()
    except Exception as e:  # noqa: BLE001
        log.warning(f"nse_pit: fetch failed: {type(e).__name__}: {e}")
        return []
    items: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        subject = (r.get("subject") or "").lower()
        desc = (r.get("smIndustry") or r.get("desc") or "").lower()
        if not any(k in subject or k in desc for k in _PIT_KEYWORDS):
            continue
        t_str = r.get("exchdisstime") or r.get("an_dt") or r.get("sort_date")
        try:
            t = (
                datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                if t_str
                else datetime.now(tz=timezone.utc)
            )
        except Exception:
            t = datetime.now(tz=timezone.utc)
        url = r.get("attchmntFile") or r.get("an_link")
        if not url:
            continue
        sym = r.get("symbol") or r.get("sym") or None
        items.append(
            {
                "time": t,
                "title": (r.get("subject") or f"NSE PIT disclosure {sym}")[:500],
                "url": url,
                "source": "nse_pit",
                "symbol": f"{sym}.NS" if sym else None,
                "summary": r.get("attchmntText") or r.get("desc") or None,
                "category": "pit_disclosure",
            }
        )
    return items


async def ingest_nse_pit(session: AsyncSession | None = None) -> int:
    log.info("ingest.nse_pit_disclosures starting")
    items = await fetch_pit_disclosures()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.nse_pit_disclosures done: {n} rows")
    return n
