"""Reddit via PRAW (read-only).

Reads hot posts from r/wallstreetbets, r/stocks, r/IndianStockMarket,
r/CryptoCurrency, r/CryptoMarkets. Stored as news rows with source=``reddit``
and category=``social``.

PRAW is synchronous; we run it in a worker thread. If REDDIT_CLIENT_ID /
REDDIT_CLIENT_SECRET are missing, the adapter no-ops.

Rate limit: Reddit enforces ~100 req/min/OAuth app; PRAW handles this for us.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.reddit_praw")

DEFAULT_SUBS: tuple[str, ...] = (
    "wallstreetbets",
    "stocks",
    "IndianStockMarket",
    "CryptoCurrency",
    "CryptoMarkets",
)


def _fetch_sync(subs: Iterable[str], limit_per_sub: int) -> list[dict[str, Any]]:
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    csec = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        log.warning("REDDIT_CLIENT_ID/SECRET not set, reddit no-op")
        return []
    try:
        import praw  # type: ignore
    except ImportError:
        log.warning("praw not installed; reddit no-op")
        return []
    reddit = praw.Reddit(
        client_id=cid, client_secret=csec, user_agent=USER_AGENT, check_for_async=False
    )
    out: list[dict[str, Any]] = []
    for sub in subs:
        try:
            for post in reddit.subreddit(sub).hot(limit=limit_per_sub):
                t = datetime.fromtimestamp(int(post.created_utc), tz=timezone.utc)
                out.append(
                    {
                        "time": t,
                        "title": post.title,
                        "url": f"https://reddit.com{post.permalink}",
                        "source": f"reddit_{sub}",
                        "symbol": None,
                        "summary": (post.selftext or "")[:1000] or None,
                        "category": "social",
                    }
                )
        except Exception as e:  # noqa: BLE001
            log.warning(f"reddit: {sub} failed: {type(e).__name__}: {e}")
            continue
    return out


async def fetch_reddit(
    subs: Iterable[str] = DEFAULT_SUBS, limit_per_sub: int = 25
) -> list[dict[str, Any]]:
    return await anyio.to_thread.run_sync(lambda: _fetch_sync(list(subs), limit_per_sub))


async def ingest_reddit(
    subs: Iterable[str] = DEFAULT_SUBS,
    limit_per_sub: int = 25,
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.reddit_praw starting")
    items = await fetch_reddit(subs, limit_per_sub)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.reddit_praw done: {n} rows")
    return n
