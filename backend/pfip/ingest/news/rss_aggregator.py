"""Convenience alias and curated bundle around :mod:`pfip.ingest.news.rss_fetcher`.

Exposes a single ``ingest_rss_aggregator`` that fans out across the default
feeds plus per-watchlist Yahoo ticker feeds when a watchlist is provided.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.news.rss_fetcher import (
    DEFAULT_FEEDS,
    fetch_feeds,
    yahoo_ticker_rss,
)

log = get_logger("pfip.ingest.news.rss_aggregator")


def build_feeds(symbols: Iterable[str] = ()) -> list[tuple[str, str, str]]:
    """Return the default feeds plus per-symbol Yahoo RSS."""
    feeds: list[tuple[str, str, str]] = list(DEFAULT_FEEDS)
    for sym in symbols:
        feeds.append(yahoo_ticker_rss(sym))
    return feeds


async def fetch_rss_aggregator(symbols: Iterable[str] = ()) -> list[dict[str, Any]]:
    return await fetch_feeds(build_feeds(symbols))


async def ingest_rss_aggregator(
    symbols: Iterable[str] = (),
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.rss_aggregator starting")
    items = await fetch_rss_aggregator(symbols)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.rss_aggregator done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_rss_aggregator())
