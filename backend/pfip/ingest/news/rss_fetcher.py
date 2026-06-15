"""Generic RSS fetcher with dedupe.

Uses the stdlib + a small bespoke parser (feedparser is the typical choice but
adds a heavy dependency). For robustness we do XML parsing via xml.etree and
fall back to feedparser if installed.

Registered feeds: see ``DEFAULT_FEEDS`` — Moneycontrol, ET Markets, LiveMint,
Business Standard, MarketWatch, Reuters public, Benzinga, CoinTelegraph,
Decrypt, The Block, CoinDesk, SEC 8-K RSS, plus Yahoo per-ticker RSS helpers.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.rss_fetcher")


# (feed_name, category, url)
DEFAULT_FEEDS: list[tuple[str, str, str]] = [
    # India
    ("moneycontrol_markets", "news", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("moneycontrol_business", "news", "https://www.moneycontrol.com/rss/business.xml"),
    ("moneycontrol_economy", "news", "https://www.moneycontrol.com/rss/economy.xml"),
    ("et_markets", "news", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("livemint_markets", "news", "https://www.livemint.com/rss/markets"),
    ("business_standard_markets", "news", "https://www.business-standard.com/rss/markets-106.rss"),
    # US
    ("marketwatch_top", "news", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    (
        "reuters_business",
        "news",
        "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    ),
    ("benzinga_news", "news", "https://www.benzinga.com/feed"),
    # Crypto
    ("cointelegraph", "news", "https://cointelegraph.com/rss"),
    ("decrypt", "news", "https://decrypt.co/feed"),
    ("theblock", "news", "https://www.theblock.co/rss.xml"),
    ("coindesk", "news", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    # Regulatory
    (
        "sec_8k",
        "sec_filing",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include&count=40&output=atom",
    ),
]


def yahoo_ticker_rss(symbol: str) -> tuple[str, str, str]:
    """Return a (name, category, url) tuple for Yahoo Finance per-ticker RSS."""
    return (
        f"yahoo_{symbol}",
        "news",
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
    )


@retry_http(max_attempts=3)
async def _download(url: str) -> bytes:
    async with get_async_client(
        headers={"Accept": "application/rss+xml,application/atom+xml,*/*"}
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def _parse_time(s: str) -> datetime:
    if not s:
        return datetime.now(tz=timezone.utc)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(tz=timezone.utc)


def _parse_feed(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Minimal RSS 2.0 + Atom parser returning list of {title,url,time,summary}."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    items: list[dict[str, Any]] = []
    ns_atom = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter():
        tag = entry.tag.split("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title_el = entry.find("title") or entry.find(f"{ns_atom}title")
        link_el = entry.find("link") or entry.find(f"{ns_atom}link")
        desc_el = (
            entry.find("description")
            or entry.find(f"{ns_atom}summary")
            or entry.find(f"{ns_atom}content")
        )
        pub_el = (
            entry.find("pubDate")
            or entry.find(f"{ns_atom}updated")
            or entry.find(f"{ns_atom}published")
        )
        title = (title_el.text or "").strip() if title_el is not None else ""
        url: str | None
        if link_el is None:
            url = None
        elif "href" in link_el.attrib:
            url = link_el.attrib["href"]
        else:
            url = (link_el.text or "").strip() or None
        if not title or not url:
            continue
        summary = (desc_el.text or "").strip() if desc_el is not None and desc_el.text else None
        t = _parse_time(pub_el.text or "") if pub_el is not None else datetime.now(tz=timezone.utc)
        items.append({"title": title, "url": url, "time": t, "summary": summary})
    return items


async def fetch_feed(name: str, category: str, url: str) -> list[dict[str, Any]]:
    try:
        raw = await _download(url)
    except Exception as e:  # noqa: BLE001
        log.warning(f"rss: {name} {url} failed: {type(e).__name__}: {e}")
        return []
    parsed = _parse_feed(raw)
    for p in parsed:
        p["source"] = name
        p["category"] = category
    return parsed


async def fetch_feeds(
    feeds: Iterable[tuple[str, str, str]] = tuple(DEFAULT_FEEDS),
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, category, url in feeds:
        out.extend(await fetch_feed(name, category, url))
    return out


async def ingest_rss(
    feeds: Iterable[tuple[str, str, str]] = tuple(DEFAULT_FEEDS),
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.rss_fetcher starting")
    items = await fetch_feeds(feeds)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.rss_fetcher done: {n} rows")
    return n
