"""Prefect flow: news / social ingest every 15 min.

Schedule: every 15 minutes.
Pulls RSS feeds, Google News per-watchlist, GDELT, Reddit, Telegram, Bluesky,
Farcaster, CryptoPanic, NewsAPI, Marketaux — whichever have usable creds.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.crypto.cryptopanic import ingest_cryptopanic
from pfip.ingest.news.bluesky import ingest_bluesky
from pfip.ingest.news.farcaster import ingest_farcaster
from pfip.ingest.news.gdelt import ingest_gdelt
from pfip.ingest.news.google_news_rss import ingest_google_news
from pfip.ingest.news.marketaux import ingest_marketaux
from pfip.ingest.news.newsapi import ingest_newsapi
from pfip.ingest.news.reddit_praw import ingest_reddit
from pfip.ingest.news.rss_fetcher import ingest_rss
from pfip.ingest.news.telegram_telethon import ingest_telegram


@task(name="rss", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _rss() -> int:
    return await ingest_rss()


@task(name="google-news", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _google(queries: list[str]) -> int:
    return await ingest_google_news(queries=queries)


@task(name="gdelt", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _gdelt() -> int:
    return await ingest_gdelt()


@task(name="reddit", retries=1, retry_delay_seconds=10)
async def _reddit() -> int:
    return await ingest_reddit()


@task(name="telegram", retries=1, retry_delay_seconds=30)
async def _telegram() -> int:
    return await ingest_telegram()


@task(name="bluesky", retries=1, retry_delay_seconds=10)
async def _bluesky() -> int:
    return await ingest_bluesky()


@task(name="farcaster", retries=1, retry_delay_seconds=10)
async def _farcaster() -> int:
    return await ingest_farcaster()


@task(name="cryptopanic", retries=1, retry_delay_seconds=10)
async def _cp() -> int:
    return await ingest_cryptopanic()


@task(name="newsapi", retries=1, retry_delay_seconds=10)
async def _newsapi() -> int:
    return await ingest_newsapi()


@task(name="marketaux", retries=1, retry_delay_seconds=10)
async def _ma() -> int:
    return await ingest_marketaux()


@flow(name="ingest-news-15min", log_prints=True)
async def ingest_news_15min(
    google_queries: Iterable[str] = (
        "RELIANCE NS",
        "TCS NS",
        "NIFTY",
        "SPY",
        "bitcoin",
    ),
) -> int:
    log = get_run_logger()
    results = await asyncio.gather(
        _rss(),
        _google(list(google_queries)),
        _gdelt(),
        _reddit(),
        _telegram(),
        _bluesky(),
        _farcaster(),
        _cp(),
        _newsapi(),
        _ma(),
        return_exceptions=True,
    )
    total = 0
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"news task failed: {type(r).__name__}: {r}")
            continue
        total += int(r)
    log.info(f"ingest-news-15min total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_news_15min())
