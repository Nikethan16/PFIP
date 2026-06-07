"""GDELT DOC 2.0 API — global news with entities + tone.

https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json

Free, no key.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.gdelt")

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

DEFAULT_QUERIES: tuple[str, ...] = (
    "bitcoin OR ethereum",
    'RBI OR "reserve bank of india"',
    "federal reserve OR FOMC",
    "nifty OR sensex",
    "inflation",
)


@retry_http(max_attempts=3)
async def _fetch(query: str, max_records: int = 75) -> dict[str, Any]:
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(max_records),
        "format": "json",
        "sort": "datedesc",
    }
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        # GDELT sometimes returns invalid JSON for empty — guard.
        try:
            return r.json()
        except Exception:
            return {}


def _parse_gdelt_time(s: str) -> datetime:
    # GDELT timestamps look like "20260421T120000Z".
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(tz=timezone.utc)


async def fetch_gdelt(queries: Iterable[str] = DEFAULT_QUERIES) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in queries:
        try:
            payload = await _fetch(q)
        except Exception as e:  # noqa: BLE001
            log.warning(f"gdelt: {q!r} failed: {type(e).__name__}: {e}")
            continue
        for art in payload.get("articles") or []:
            url = art.get("url")
            title = art.get("title") or ""
            if not url:
                continue
            t = _parse_gdelt_time(art.get("seendate") or "")
            tone = art.get("tone")
            sentiment = None
            if isinstance(tone, (int, float)):
                # GDELT tone is roughly in [-10, 10]. Map to [-1, 1].
                sentiment = max(-1.0, min(1.0, float(tone) / 10.0))
            out.append(
                {
                    "time": t,
                    "title": title,
                    "url": url,
                    "source": "gdelt",
                    "symbol": None,
                    "sentiment": sentiment,
                    "summary": art.get("domain"),
                    "category": "news",
                }
            )
    return out


async def ingest_gdelt(
    queries: Iterable[str] = DEFAULT_QUERIES, session: AsyncSession | None = None
) -> int:
    log.info("ingest.gdelt starting")
    items = await fetch_gdelt(queries)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.gdelt done: {n} rows")
    return n
