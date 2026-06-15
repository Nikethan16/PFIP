"""Farcaster casts via Neynar REST API.

Endpoints:
- https://api.neynar.com/v2/farcaster/feed/search?q=...&limit=50
- https://api.neynar.com/v2/farcaster/feed/trending

Requires NEYNAR_API_KEY header ``api_key``. No-ops if missing.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.farcaster")

BASE = "https://api.neynar.com/v2/farcaster"


@retry_http(max_attempts=3)
async def _search(query: str, api_key: str, limit: int = 25) -> dict[str, Any]:
    async with get_async_client(
        headers={"api_key": api_key, "accept": "application/json"}
    ) as client:
        r = await client.get(f"{BASE}/feed/search", params={"q": query, "limit": str(limit)})
        r.raise_for_status()
        return r.json()


async def fetch_farcaster(
    queries: Iterable[str] = ("bitcoin", "base", "defi")
) -> list[dict[str, Any]]:
    key = os.environ.get("NEYNAR_API_KEY", "").strip()
    if not key:
        log.warning("NEYNAR_API_KEY not set, farcaster no-op")
        return []
    out: list[dict[str, Any]] = []
    for q in queries:
        try:
            resp = await _search(q, key)
        except Exception as e:  # noqa: BLE001
            log.warning(f"farcaster: {q!r} failed: {type(e).__name__}: {e}")
            continue
        for cast in resp.get("casts") or []:
            hash_ = cast.get("hash")
            if not hash_:
                continue
            ts = cast.get("timestamp")
            try:
                t = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if ts
                    else datetime.now(tz=timezone.utc)
                )
            except Exception:
                t = datetime.now(tz=timezone.utc)
            author = (cast.get("author") or {}).get("username")
            url = (
                f"https://warpcast.com/{author}/{hash_[:10]}" if author else f"farcaster://{hash_}"
            )
            out.append(
                {
                    "time": t,
                    "title": (cast.get("text") or "")[:300],
                    "url": url,
                    "source": "farcaster",
                    "summary": f"fid={cast.get('author', {}).get('fid')} query={q}",
                    "category": "social",
                }
            )
    return out


async def ingest_farcaster(
    queries: Iterable[str] = ("bitcoin", "base", "defi"),
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.farcaster starting")
    items = await fetch_farcaster(queries)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.farcaster done: {n} rows")
    return n
