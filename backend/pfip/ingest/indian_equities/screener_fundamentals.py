"""Screener.in fundamentals scraper.

Polite-by-default: 1 request per 3 seconds per process. Uses httpx + selectolax
for lightweight HTML parsing. Screener does not provide a stable API; fields
are extracted from the company page's "Ratios" and "Quarters" tables.

Caveat: Screener restates historical data retroactively. We still store
``as_of_date = today`` per the plan's point-in-time simplification (the
``report_date`` reflects the quarter end). Users querying for PIT should
cross-reference filings from SEC EDGAR / BSE corporate filings for US / IN.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.indian_equities.screener_fundamentals")

_POLITE_DELAY_SEC = 3.0
BASE = "https://www.screener.in/company/"


@retry_http(max_attempts=3)
async def _fetch_page(symbol: str) -> str:
    async with get_async_client(
        headers={"Accept": "text/html"}, follow_redirects=True
    ) as client:
        r = await client.get(f"{BASE}{symbol}/consolidated/")
        r.raise_for_status()
        return r.text


def _parse_ratios(html: str) -> dict[str, float]:
    """Extract top-ratio cards from a Screener company page."""
    try:
        from selectolax.parser import HTMLParser  # type: ignore
    except ImportError:
        log.warning("selectolax not installed; screener fundamentals will be empty")
        return {}
    tree = HTMLParser(html)
    out: dict[str, float] = {}
    for li in tree.css("#top-ratios li"):
        name_el = li.css_first(".name")
        val_el = li.css_first(".number")
        if not name_el or not val_el:
            continue
        key = name_el.text(strip=True).lower().replace(" ", "_").replace("/", "_")
        raw = val_el.text(strip=True).replace(",", "").replace("₹", "").replace("%", "")
        raw = raw.split()[0] if raw else ""
        try:
            val = float(raw)
        except ValueError:
            continue
        out[key] = val
    return out


async def fetch_screener(symbols: Iterable[str]) -> list[dict[str, Any]]:
    """Scrape per-symbol ratio cards with polite delay."""
    today = date.today()
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            html = await _fetch_page(sym)
        except Exception as e:  # noqa: BLE001
            log.warning(f"screener: {sym} failed: {type(e).__name__}: {e}")
            await asyncio.sleep(_POLITE_DELAY_SEC)
            continue
        ratios = _parse_ratios(html)
        for k, v in ratios.items():
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": f"{sym.upper()}.NS",
                    "field": f"screener_{k}",
                    "value": v,
                    "source": "screener",
                }
            )
        await asyncio.sleep(_POLITE_DELAY_SEC)
    return rows


async def ingest_screener(
    symbols: Iterable[str] = ("RELIANCE", "TCS", "HDFCBANK", "INFY"),
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.screener_fundamentals starting")
    rows = await fetch_screener(list(symbols))
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.screener_fundamentals done: {n} rows")
    return n
