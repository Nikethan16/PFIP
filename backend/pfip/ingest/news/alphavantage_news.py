"""Alpha Vantage NEWS_SENTIMENT — requires ALPHAVANTAGE_API_KEY.

General financial-market news with an AI sentiment score per article (and per
ticker). Free tier is ~25 requests/day, so the daily pipeline makes one call.
No-op (returns 0) when the key isn't set — mirrors the other keyed adapters.
https://www.alphavantage.co/documentation/#news-sentiment
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

log = get_logger("pfip.ingest.news.alphavantage_news")

BASE = "https://www.alphavantage.co/query"


def _parse_time(s: str | None) -> datetime:
    # Alpha Vantage time_published format: "20260629T103000"
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


@retry_http(max_attempts=3)
async def _fetch(api_key: str, topics: str) -> dict[str, Any]:
    params = {
        "function": "NEWS_SENTIMENT",
        "apikey": api_key,
        "topics": topics,
        "sort": "LATEST",
        "limit": "50",
    }
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_alphavantage_news(topics: str = "financial_markets") -> list[dict[str, Any]]:
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not key:
        log.warning("ALPHAVANTAGE_API_KEY not set, alphavantage_news no-op")
        return []
    try:
        resp = await _fetch(key, topics)
    except Exception as e:  # noqa: BLE001
        log.warning(f"alphavantage_news: failed: {type(e).__name__}: {e}")
        return []
    out: list[dict[str, Any]] = []
    for art in resp.get("feed") or []:
        url = art.get("url")
        if not url:
            continue
        # First ticker, stripping the CRYPTO:/FOREX: prefix AV uses.
        tickers = art.get("ticker_sentiment") or []
        symbol = None
        if tickers:
            raw = str(tickers[0].get("ticker") or "")
            symbol = raw.split(":")[-1] or None
        try:
            sent = (
                float(art["overall_sentiment_score"])
                if art.get("overall_sentiment_score") is not None
                else None
            )
        except Exception:
            sent = None
        out.append(
            {
                "time": _parse_time(art.get("time_published")),
                "title": art.get("title") or "",
                "url": url,
                "source": "alphavantage",
                "symbol": symbol,
                "sentiment": sent,
                "summary": art.get("summary"),
                "category": "news",
            }
        )
    return out


async def ingest_alphavantage_news(session: AsyncSession | None = None) -> int:
    log.info("ingest.alphavantage_news starting")
    items = await fetch_alphavantage_news()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.alphavantage_news done: {n} rows")
    return n
