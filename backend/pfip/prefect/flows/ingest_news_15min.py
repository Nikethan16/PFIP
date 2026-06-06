"""Prefect flow: news / social ingest every 15 min.

Schedule: every 15 minutes.
Pulls RSS feeds, Google News per-watchlist, GDELT, Reddit, Telegram, Bluesky,
Farcaster, CryptoPanic, NewsAPI, Marketaux — whichever have usable creds.

Resilience
----------
External news/social sources regularly return 403/404/429 or simply hang
(slow CDNs, rate limits, dead feeds). Each source call is therefore wrapped in
``asyncio.wait_for`` with a per-source wall-clock budget so a single hanging
source cannot head-of-line-block the Prefect worker for the whole 15-min slot.
Every adapter is idempotent (upserts) and non-fatal: on timeout/error we log a
warning and contribute 0 rows, letting the rest of the sources proceed.

Per-source timeouts are generous enough for the multi-feed adapters (RSS and
Google News iterate many feeds sequentially) while still bounding the flow.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Iterable

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

# Per-source wall-clock budgets (seconds). Multi-feed adapters (RSS, Google
# News) iterate many upstream feeds sequentially so they get a larger budget;
# single-endpoint adapters get the default. These bound how long one source can
# stall the flow regardless of any per-request HTTP timeout/retry inside it.
_DEFAULT_SOURCE_TIMEOUT = 45.0
_RSS_TIMEOUT = 90.0
_GOOGLE_TIMEOUT = 90.0


async def _guard(
    name: str,
    coro_factory: Callable[[], Awaitable[int]],
    timeout: float = _DEFAULT_SOURCE_TIMEOUT,
) -> int:
    """Run a source ingest under a wall-clock timeout; never raise.

    Returns the row count on success, or 0 on timeout/error (logged as a
    warning). Keeps the flow idempotent and non-fatal so one hanging or failing
    source cannot block the others or the worker.
    """
    log = get_run_logger()
    try:
        return int(await asyncio.wait_for(coro_factory(), timeout=timeout))
    except asyncio.TimeoutError:
        log.warning(f"news source {name!r} timed out after {timeout:.0f}s; skipping")
        return 0
    except Exception as e:  # noqa: BLE001
        log.warning(f"news source {name!r} failed: {type(e).__name__}: {e}")
        return 0


@task(name="rss", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _rss() -> int:
    return await _guard("rss", ingest_rss, timeout=_RSS_TIMEOUT)


@task(name="google-news", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _google(queries: list[str]) -> int:
    return await _guard("google-news", lambda: ingest_google_news(queries=queries), timeout=_GOOGLE_TIMEOUT)


@task(name="gdelt", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=5))
async def _gdelt() -> int:
    return await _guard("gdelt", ingest_gdelt)


@task(name="reddit", retries=1, retry_delay_seconds=10)
async def _reddit() -> int:
    return await _guard("reddit", ingest_reddit)


@task(name="telegram", retries=1, retry_delay_seconds=30)
async def _telegram() -> int:
    return await _guard("telegram", ingest_telegram)


@task(name="bluesky", retries=1, retry_delay_seconds=10)
async def _bluesky() -> int:
    return await _guard("bluesky", ingest_bluesky)


@task(name="farcaster", retries=1, retry_delay_seconds=10)
async def _farcaster() -> int:
    return await _guard("farcaster", ingest_farcaster)


@task(name="cryptopanic", retries=1, retry_delay_seconds=10)
async def _cp() -> int:
    return await _guard("cryptopanic", ingest_cryptopanic)


@task(name="newsapi", retries=1, retry_delay_seconds=10)
async def _newsapi() -> int:
    return await _guard("newsapi", ingest_newsapi)


@task(name="marketaux", retries=1, retry_delay_seconds=10)
async def _ma() -> int:
    return await _guard("marketaux", ingest_marketaux)


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
