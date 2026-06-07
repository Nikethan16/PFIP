"""Finnhub earnings + economic calendar.

Thin facade over ``pfip.ingest.us_equities.finnhub_fundamentals.fetch_earnings_calendar``
plus the economic calendar endpoint. Stored as news with the relevant category.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.us_equities.finnhub_fundamentals import fetch_earnings_calendar

log = get_logger("pfip.ingest.economic_calendar.finnhub_calendar")

ECON_URL = "https://finnhub.io/api/v1/calendar/economic"


@retry_http(max_attempts=3)
async def _fetch_econ(api_key: str, days_ahead: int = 30) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    params = {
        "from": now.date().isoformat(),
        "to": (now + timedelta(days=days_ahead)).date().isoformat(),
        "token": api_key,
    }
    async with get_async_client() as client:
        r = await client.get(ECON_URL, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_economic_calendar(days_ahead: int = 30) -> list[dict[str, Any]]:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        log.warning("FINNHUB_API_KEY not set, econ calendar no-op")
        return []
    try:
        resp = await _fetch_econ(key, days_ahead)
    except Exception as e:  # noqa: BLE001
        log.warning(f"finnhub econ calendar failed: {type(e).__name__}: {e}")
        return []
    events = resp.get("economicCalendar") or []
    items: list[dict[str, Any]] = []
    for e in events:
        t_str = e.get("time") or e.get("date")
        if not t_str:
            continue
        try:
            t = datetime.fromisoformat(str(t_str).replace("Z", "+00:00"))
        except Exception:
            try:
                t = datetime.fromisoformat(str(t_str))
            except Exception:
                continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        evt = e.get("event") or "econ"
        country = e.get("country") or ""
        url = f"pfip://finnhub/econ/{country}/{evt}/{t.isoformat()}"
        items.append(
            {
                "time": t,
                "title": f"{country} {evt} ({e.get('impact') or 'low'})",
                "url": url,
                "source": "finnhub_econ",
                "symbol": None,
                "summary": f"actual={e.get('actual')} prev={e.get('prev')} est={e.get('estimate')}",
                "category": "econ_calendar",
            }
        )
    return items


async def ingest_finnhub_calendar(days_ahead: int = 30, session: AsyncSession | None = None) -> int:
    log.info("ingest.finnhub_calendar starting")
    earnings = await fetch_earnings_calendar(days_ahead=days_ahead)
    econ = await fetch_economic_calendar(days_ahead=days_ahead)
    all_items = earnings + econ
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, all_items)
    else:
        n = await upsert_news(session, all_items)
    log.info(f"ingest.finnhub_calendar done: {n} rows")
    return n
