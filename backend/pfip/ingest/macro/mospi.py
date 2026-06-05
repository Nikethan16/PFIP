"""MOSPI — Ministry of Statistics & Programme Implementation (India).

MOSPI publishes CPI, IIP, GDP press releases. No formal API; they post press
release PDFs and an Excel data dump. We use the RSS-style "What's New" feed
when accessible and a polite scrape of the "data releases" page as fallback.

This adapter is best-effort: MOSPI's site is notoriously unreliable. On any
failure we no-op and the macro pipeline relies on DBnomics' MOSPI mirror.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.macro.mospi")

WHATS_NEW = "https://www.mospi.gov.in/whats-new"
PRESS_RSS = "https://www.mospi.gov.in/rss-feed-pressrelease"


@retry_http(max_attempts=2)
async def _fetch(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Accept": "application/rss+xml,text/html,*/*",
    }
    async with get_async_client(headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


def _parse_press_rss(xml: str) -> list[dict[str, Any]]:
    """Minimal RSS extraction; mirrors pfip.ingest.news.rss_fetcher conventions."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate") or ""
        if not title or not link:
            continue
        try:
            t = parsedate_to_datetime(pub)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except Exception:
            t = datetime.now(tz=timezone.utc)
        desc = (item.findtext("description") or "").strip()
        out.append(
            {
                "time": t,
                "title": title,
                "url": link,
                "source": "mospi",
                "category": "macro_release",
                "summary": desc or None,
            }
        )
    return out


async def fetch_mospi_releases() -> list[dict[str, Any]]:
    try:
        xml = await _fetch(PRESS_RSS)
    except Exception as e:  # noqa: BLE001
        log.warning(f"mospi: rss fetch failed: {type(e).__name__}: {e}")
        return []
    return _parse_press_rss(xml)


async def ingest_mospi(session: AsyncSession | None = None) -> int:
    log.info("ingest.mospi starting")
    items = await fetch_mospi_releases()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            from pfip.ingest._common.upsert import upsert_news

            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.mospi done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_mospi())
