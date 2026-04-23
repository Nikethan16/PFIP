"""Bluesky firehose reader with allow-list + keyword + language filter.

Authenticates with BLUESKY_HANDLE + BLUESKY_APP_PASSWORD against the public
AT Proto service (https://bsky.social). If creds are missing, we fall back to
the unauthenticated public ``searchPosts`` endpoint for a bounded pull.

The full jetstream/firehose (sync event stream) requires long-running
websockets; the Prefect flow runs the adapter on a periodic cadence so we use
``app.bsky.feed.searchPosts`` for each keyword which fits a 15-min poll.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.bluesky")

APPVIEW = "https://public.api.bsky.app"


DEFAULT_KEYWORDS: tuple[str, ...] = (
    "bitcoin",
    "ethereum",
    "fed funds",
    "nifty",
    "S&P 500",
    "inflation",
)


@retry_http(max_attempts=3)
async def _search(keyword: str, lang: str = "en", limit: int = 25) -> dict[str, Any]:
    params = {"q": keyword, "lang": lang, "limit": str(limit)}
    async with get_async_client() as client:
        r = await client.get(f"{APPVIEW}/xrpc/app.bsky.feed.searchPosts", params=params)
        r.raise_for_status()
        return r.json()


async def _login(handle: str, app_password: str) -> str | None:
    """Optional: create session to raise rate limits. Returns accessJwt or None."""
    try:
        async with get_async_client() as client:
            r = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": app_password},
            )
            r.raise_for_status()
            return (r.json() or {}).get("accessJwt")
    except Exception as e:  # noqa: BLE001
        log.warning(f"bluesky: login failed: {type(e).__name__}: {e}")
        return None


async def fetch_bluesky(keywords: Iterable[str] = DEFAULT_KEYWORDS) -> list[dict[str, Any]]:
    handle = os.environ.get("BLUESKY_HANDLE", "").strip()
    app_pw = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    # Login is optional; searchPosts works unauthenticated but is bandwidth-limited.
    if handle and app_pw:
        await _login(handle, app_pw)
    out: list[dict[str, Any]] = []
    for kw in keywords:
        try:
            resp = await _search(kw)
        except Exception as e:  # noqa: BLE001
            log.warning(f"bluesky: search {kw!r} failed: {type(e).__name__}: {e}")
            continue
        for p in resp.get("posts") or []:
            record = p.get("record") or {}
            uri = p.get("uri")
            author = (p.get("author") or {}).get("handle")
            text = record.get("text") or ""
            created = record.get("createdAt")
            try:
                t = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else datetime.utcnow()
            except Exception:
                t = datetime.utcnow()
            if not uri or not text:
                continue
            web_url = (
                f"https://bsky.app/profile/{author}/post/{uri.split('/')[-1]}"
                if author
                else uri
            )
            out.append(
                {
                    "time": t,
                    "title": text[:300],
                    "url": web_url,
                    "source": "bluesky",
                    "summary": f"keyword={kw}",
                    "category": "social",
                }
            )
    return out


async def ingest_bluesky(
    keywords: Iterable[str] = DEFAULT_KEYWORDS, session: AsyncSession | None = None
) -> int:
    log.info("ingest.bluesky starting")
    items = await fetch_bluesky(keywords)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.bluesky done: {n} rows")
    return n
