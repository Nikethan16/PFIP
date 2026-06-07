"""NewsAPI.org — requires NEWSAPI_API_KEY.

https://newsapi.org/v2/everything?q=...&from=...&sortBy=publishedAt

Free tier is restricted to dev use (100 req/day, 1 month of data). No-ops if
the key is missing.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.newsapi")

BASE = "https://newsapi.org/v2/everything"


@retry_http(max_attempts=3)
async def _fetch(query: str, api_key: str) -> dict[str, Any]:
    frm = (datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat()
    params = {
        "q": query,
        "from": frm,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": "50",
    }
    async with get_async_client(headers={"X-Api-Key": api_key}) as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_newsapi(queries: Iterable[str]) -> list[dict[str, Any]]:
    key = os.environ.get("NEWSAPI_API_KEY", "").strip()
    if not key:
        log.warning("NEWSAPI_API_KEY not set, newsapi no-op")
        return []
    out: list[dict[str, Any]] = []
    for q in queries:
        try:
            resp = await _fetch(q, key)
        except Exception as e:  # noqa: BLE001
            log.warning(f"newsapi: {q!r} failed: {type(e).__name__}: {e}")
            continue
        for art in resp.get("articles") or []:
            url = art.get("url")
            if not url:
                continue
            t_str = art.get("publishedAt")
            try:
                t = (
                    datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                    if t_str
                    else datetime.now(tz=timezone.utc)
                )
            except Exception:
                t = datetime.now(tz=timezone.utc)
            out.append(
                {
                    "time": t,
                    "title": art.get("title") or "",
                    "url": url,
                    "source": "newsapi",
                    "symbol": None,
                    "summary": (art.get("source") or {}).get("name"),
                    "category": "news",
                }
            )
    return out


async def ingest_newsapi(
    queries: Iterable[str] = ("stocks", "bitcoin", "NIFTY"),
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.newsapi starting")
    items = await fetch_newsapi(queries)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.newsapi done: {n} rows")
    return n
