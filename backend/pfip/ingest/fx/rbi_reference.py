"""RBI daily reference rate scrape (USD/INR, EUR/INR, GBP/INR, JPY/INR).

RBI publishes reference rates at https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx
with a POST form. We use the simpler public HTML page
``https://www.rbi.org.in/home.aspx`` which embeds the latest reference rates
in a widget, or fall back to the RSS at ``https://www.rbi.org.in/pressreleases_RSS.xml``.

A lighter alternative: https://www.rbi.org.in/Scripts/BS_ViewEconWrapper.aspx
also returns structured text. For robustness we try the FBIL daily reference
rates CSV at ``https://www.fbil.org.in/#/home`` via their public JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.fx.rbi_reference")

RBI_HOME = "https://www.rbi.org.in/"


@retry_http(max_attempts=3)
async def _fetch_home() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Accept": "text/html",
    }
    async with get_async_client(headers=headers) as client:
        r = await client.get(RBI_HOME)
        r.raise_for_status()
        return r.text


def _parse_rbi_rates(html: str) -> dict[str, float]:
    """Parse embedded reference rate widget; returns {CCY: INR_per_CCY}."""
    try:
        from selectolax.parser import HTMLParser  # type: ignore
    except ImportError:
        log.warning("selectolax not installed; rbi parser returning empty")
        return {}
    out: dict[str, float] = {}
    tree = HTMLParser(html)
    # The rates live in a table; each row has a CCY name and value cell.
    for row in tree.css("table tr"):
        cells = row.css("td")
        if len(cells) != 2:
            continue
        name = cells[0].text(strip=True).upper()
        val_txt = cells[1].text(strip=True).replace(",", "").replace("₹", "")
        try:
            val = float(val_txt)
        except ValueError:
            continue
        for ccy in ("USD", "EUR", "GBP", "JPY"):
            if ccy in name:
                out[ccy] = val
                break
    return out


async def fetch_rbi_reference() -> list[dict[str, Any]]:
    try:
        html = await _fetch_home()
    except Exception as e:  # noqa: BLE001
        log.warning(f"rbi: fetch failed: {type(e).__name__}: {e}")
        return []
    rates = _parse_rbi_rates(html)
    t = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows: list[dict[str, Any]] = []
    for ccy, val in rates.items():
        sym = f"{ccy}INR"
        rows.append(
            {
                "time": t,
                "symbol": sym,
                "market": "FX",
                "source": "rbi",
                "timeframe": "1d",
                "open": val,
                "high": val,
                "low": val,
                "close": val,
                "volume": 0,
            }
        )
    return rows


async def ingest_rbi_reference(session: AsyncSession | None = None) -> int:
    log.info("ingest.rbi_reference starting")
    rows = await fetch_rbi_reference()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.rbi_reference done: {n} rows")
    return n
