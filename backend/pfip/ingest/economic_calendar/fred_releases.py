"""FRED release schedule — upcoming US data releases.

Endpoint: ``https://api.stlouisfed.org/fred/releases/dates?api_key=...&file_type=json``
Stored as news rows with category=``econ_calendar``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.economic_calendar.fred_releases")

BASE = "https://api.stlouisfed.org/fred/releases/dates"


@retry_http(max_attempts=3)
async def _fetch(api_key: str) -> dict[str, Any]:
    params = {
        "api_key": api_key,
        "file_type": "json",
        "include_release_dates_with_no_data": "false",
        "limit": "1000",
        "sort_order": "asc",
    }
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_fred_releases() -> list[dict[str, Any]]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        log.warning("FRED_API_KEY not set, fred_releases no-op")
        return []
    try:
        resp = await _fetch(key)
    except Exception as e:  # noqa: BLE001
        log.warning(f"fred_releases: failed: {type(e).__name__}: {e}")
        return []
    dates = resp.get("release_dates") or []
    items: list[dict[str, Any]] = []
    for row in dates:
        d_str = row.get("date")
        rid = row.get("release_id")
        name = row.get("release_name")
        if not d_str or not rid:
            continue
        try:
            t = datetime.fromisoformat(d_str).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        url = f"https://fred.stlouisfed.org/release?rid={rid}&date={d_str}"
        items.append(
            {
                "time": t,
                "title": f"FRED release: {name or rid}",
                "url": url,
                "source": "fred_releases",
                "summary": f"release_id={rid}",
                "category": "econ_calendar",
            }
        )
    return items


async def ingest_fred_releases(session: AsyncSession | None = None) -> int:
    log.info("ingest.fred_releases starting")
    items = await fetch_fred_releases()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.fred_releases done: {n} rows")
    return n
