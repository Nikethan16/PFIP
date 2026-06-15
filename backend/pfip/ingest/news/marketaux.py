"""Marketaux financial news API — requires MARKETAUX_API_KEY.

https://api.marketaux.com/v1/news/all?api_token=...&countries=us,in&limit=50
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

log = get_logger("pfip.ingest.news.marketaux")

BASE = "https://api.marketaux.com/v1/news/all"


@retry_http(max_attempts=3)
async def _fetch(api_key: str, countries: str) -> dict[str, Any]:
    params = {"api_token": api_key, "countries": countries, "language": "en", "limit": "50"}
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_marketaux(countries: str = "us,in") -> list[dict[str, Any]]:
    key = os.environ.get("MARKETAUX_API_KEY", "").strip()
    if not key:
        log.warning("MARKETAUX_API_KEY not set, marketaux no-op")
        return []
    try:
        resp = await _fetch(key, countries)
    except Exception as e:  # noqa: BLE001
        log.warning(f"marketaux: failed: {type(e).__name__}: {e}")
        return []
    out: list[dict[str, Any]] = []
    for art in resp.get("data") or []:
        url = art.get("url")
        if not url:
            continue
        t_str = art.get("published_at")
        try:
            t = (
                datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                if t_str
                else datetime.now(tz=timezone.utc)
            )
        except Exception:
            t = datetime.now(tz=timezone.utc)
        entities = art.get("entities") or []
        symbol = entities[0].get("symbol") if entities else None
        out.append(
            {
                "time": t,
                "title": art.get("title") or "",
                "url": url,
                "source": "marketaux",
                "symbol": symbol,
                "sentiment": (
                    art.get("sentiment") if isinstance(art.get("sentiment"), (int, float)) else None
                ),
                "summary": art.get("snippet") or art.get("description"),
                "category": "news",
            }
        )
    return out


async def ingest_marketaux(session: AsyncSession | None = None) -> int:
    log.info("ingest.marketaux starting")
    items = await fetch_marketaux()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.marketaux done: {n} rows")
    return n
