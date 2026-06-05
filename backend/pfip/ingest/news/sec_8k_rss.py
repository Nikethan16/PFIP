"""SEC 8-K real-time material filings via the EDGAR Atom feed.

URL: ``https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include&count=40&output=atom``

This delivers the firehose of all 8-K filings (across all issuers) so we can
catch acquisitions, leadership changes, earnings preannouncements as they hit
EDGAR. Per SEC guidance we provide a descriptive User-Agent.

Stored as news rows with ``category='sec_filing'``. The 8-K-per-issuer detail
(when an issuer is a tracked watchlist symbol) is left to a downstream
classifier; here we only ingest the headline.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.news.rss_fetcher import _parse_feed

log = get_logger("pfip.ingest.news.sec_8k_rss")

SEC_8K_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&type=8-K&dateb=&owner=include&count=40&output=atom"
)


def _sec_headers() -> dict[str, str]:
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", USER_AGENT).strip() or USER_AGENT
    return {"User-Agent": ua, "Accept": "application/atom+xml,application/rss+xml,*/*"}


@retry_http(max_attempts=3)
async def _download() -> bytes:
    async with get_async_client(headers=_sec_headers()) as client:
        r = await client.get(SEC_8K_URL)
        r.raise_for_status()
        return r.content


async def fetch_sec_8k() -> list[dict[str, Any]]:
    try:
        raw = await _download()
    except Exception as e:  # noqa: BLE001
        log.warning(f"sec_8k_rss: download failed: {type(e).__name__}: {e}")
        return []
    items = _parse_feed(raw)
    for it in items:
        it["source"] = "sec_8k"
        it["category"] = "sec_filing"
    return items


async def ingest_sec_8k_rss(session: AsyncSession | None = None) -> int:
    log.info("ingest.sec_8k_rss starting")
    items = await fetch_sec_8k()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.sec_8k_rss done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_sec_8k_rss())
