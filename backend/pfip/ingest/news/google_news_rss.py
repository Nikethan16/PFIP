"""Google News per-query RSS.

URL format: ``https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en``
Works without a key. We build one RSS URL per watchlist ticker/query and
reuse the generic RSS parser.
"""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.news.rss_fetcher import fetch_feed

log = get_logger("pfip.ingest.news.google_news_rss")


def build_query_url(query: str, *, hl: str = "en-IN", gl: str = "IN") -> str:
    q = quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{hl.split('-')[0]}"


async def fetch_google_news(queries: Iterable[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in queries:
        feed_name = f"google_news_{q[:40]}"
        items = await fetch_feed(feed_name, "news", build_query_url(q))
        for it in items:
            it["summary"] = f"Query: {q} | " + (it.get("summary") or "")
        out.extend(items)
    return out


async def ingest_google_news(
    queries: Iterable[str] = ("RELIANCE", "TCS", "NIFTY", "S&P 500"),
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.google_news_rss starting")
    items = await fetch_google_news(queries)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.google_news_rss done: {n} rows")
    return n
