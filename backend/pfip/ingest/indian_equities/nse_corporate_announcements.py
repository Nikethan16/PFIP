"""NSE corporate announcements via the public RSS-like feed.

NSE offers JSON endpoints for announcements (subject to anti-bot measures).
We use the simpler public RSS at ``https://nsearchives.nseindia.com/content/
RSS/Online_announcements.xml`` when available, falling back to the
``https://www.nseindia.com/api/corporate-announcements?index=equities`` JSON.

Stored as news rows with category=``corp_announcement``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import BROWSER_UA, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.news.rss_fetcher import _parse_feed

log = get_logger("pfip.ingest.indian_equities.nse_corporate_announcements")

RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
JSON_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json,application/rss+xml,text/xml;q=0.9,*/*",
        "Referer": "https://www.nseindia.com/",
        "Accept-Language": "en-IN,en;q=0.9",
    }


@retry_http(max_attempts=2)
async def _get(url: str) -> tuple[bytes, str]:
    async with get_async_client(headers=_browser_headers()) as client:
        # NSE requires a session cookie from the home page first.
        try:
            await client.get("https://www.nseindia.com", timeout=10.0)
        except Exception:
            pass
        r = await client.get(url)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "")


def _from_json(payload: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except Exception:
        return []
    items = data if isinstance(data, list) else (data.get("data") or data.get("rows") or [])
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sym = (it.get("symbol") or "").strip().upper() or None
        title = (it.get("desc") or it.get("subject") or it.get("an_dt") or "").strip()
        link = (it.get("attchmntFile") or it.get("an_dt") or "").strip()
        tstr = (it.get("an_dt") or it.get("disseminationTime") or "").strip()
        if not title:
            continue
        try:
            t = datetime.strptime(tstr, "%d-%b-%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            t = datetime.now(tz=timezone.utc)
        url = (
            link
            if link.startswith("http")
            else f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={sym}"
        )
        out.append(
            {
                "time": t,
                "title": title[:1000],
                "url": url,
                "source": "nse_announcements",
                "category": "corp_announcement",
                "symbol": sym,
            }
        )
    return out


async def fetch_nse_announcements() -> list[dict[str, Any]]:
    # Try RSS first (lighter, no anti-bot).
    try:
        raw, _ctype = await _get(RSS_URL)
        items = _parse_feed(raw)
        if items:
            for it in items:
                it.setdefault("source", "nse_announcements")
                it.setdefault("category", "corp_announcement")
            return items
    except Exception as e:  # noqa: BLE001
        log.warning(f"nse_corp_ann: RSS failed: {type(e).__name__}: {e}")

    # Fall back to JSON.
    try:
        raw, _ = await _get(JSON_URL)
        return _from_json(raw)
    except Exception as e:  # noqa: BLE001
        log.warning(f"nse_corp_ann: JSON failed: {type(e).__name__}: {e}")
        return []


async def ingest_nse_corporate_announcements(
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.nse_corporate_announcements starting")
    items = await fetch_nse_announcements()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.nse_corporate_announcements done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_nse_corporate_announcements())
