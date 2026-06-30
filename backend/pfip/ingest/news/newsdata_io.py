"""NewsData.io business/market news — requires NEWSDATA_API_KEY.

India- and US-aware business news; free tier ~200 credits/day. No-op when the
key isn't set. https://newsdata.io/documentation
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

log = get_logger("pfip.ingest.news.newsdata_io")

BASE = "https://newsdata.io/api/1/news"


def _parse_time(s: str | None) -> datetime:
    # NewsData pubDate: "2026-06-29 10:30:00" (UTC).
    try:
        return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


@retry_http(max_attempts=3)
async def _fetch(api_key: str, country: str) -> dict[str, Any]:
    params = {
        "apikey": api_key,
        "category": "business",
        "language": "en",
        "country": country,
    }
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_newsdata(country: str = "in,us") -> list[dict[str, Any]]:
    key = os.environ.get("NEWSDATA_API_KEY", "").strip()
    if not key:
        log.warning("NEWSDATA_API_KEY not set, newsdata_io no-op")
        return []
    try:
        resp = await _fetch(key, country)
    except Exception as e:  # noqa: BLE001
        log.warning(f"newsdata_io: failed: {type(e).__name__}: {e}")
        return []
    out: list[dict[str, Any]] = []
    for art in resp.get("results") or []:
        url = art.get("link")
        if not url:
            continue
        out.append(
            {
                "time": _parse_time(art.get("pubDate")),
                "title": art.get("title") or "",
                "url": url,
                "source": "newsdata",
                "symbol": None,  # NewsData free tier has no ticker tagging
                "sentiment": None,  # sentiment is a paid add-on
                "summary": art.get("description"),
                "category": "news",
            }
        )
    return out


async def ingest_newsdata(session: AsyncSession | None = None) -> int:
    log.info("ingest.newsdata_io starting")
    items = await fetch_newsdata()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.newsdata_io done: {n} rows")
    return n
