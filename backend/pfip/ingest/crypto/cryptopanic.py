"""CryptoPanic crypto news aggregator.

Uses the public posts endpoint. A free-tier auth token is optional; without it
we fall back to the public unauthenticated endpoint which returns a smaller set.

https://cryptopanic.com/developers/api/
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.crypto.cryptopanic")

BASE = "https://cryptopanic.com/api/v1/posts/"


@retry_http(max_attempts=3)
async def _fetch(params: dict[str, Any]) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_cryptopanic_posts(
    filter_: str = "hot",
    kind: str = "news",
    currencies: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch a single page of crypto news items."""
    params: dict[str, Any] = {"public": "true", "filter": filter_, "kind": kind}
    key = os.environ.get("CRYPTOPANIC_API_KEY", "").strip()
    if key:
        params["auth_token"] = key
    if currencies:
        params["currencies"] = currencies
    try:
        payload = await _fetch(params)
    except Exception as e:  # noqa: BLE001
        log.warning(f"cryptopanic: fetch failed: {type(e).__name__}: {e}")
        return []
    results = payload.get("results") or []
    items: list[dict[str, Any]] = []
    for p in results:
        url = p.get("url") or p.get("source", {}).get("url")
        if not url:
            continue
        t_str = p.get("published_at") or p.get("created_at")
        try:
            t = datetime.fromisoformat(t_str.replace("Z", "+00:00")) if t_str else datetime.utcnow()
        except Exception:
            t = datetime.utcnow()
        symbols = p.get("currencies") or []
        symbol = symbols[0].get("code") if symbols else None
        items.append(
            {
                "time": t,
                "title": p.get("title") or "",
                "url": url,
                "source": "cryptopanic",
                "symbol": symbol,
                "sentiment": None,
                "summary": (p.get("domain") or "") + ": " + (p.get("title") or ""),
                "category": "news",
            }
        )
    return items


async def ingest_cryptopanic(session: AsyncSession | None = None) -> int:
    """Fetch a batch of CryptoPanic posts and upsert into news."""
    log.info("ingest.cryptopanic starting")
    items = await fetch_cryptopanic_posts()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.cryptopanic done: {n} rows")
    return n
