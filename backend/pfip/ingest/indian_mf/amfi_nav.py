"""AMFI daily NAV feed.

Endpoint: https://www.amfiindia.com/spages/NAVAll.txt (tab/semicolon-delimited).
The file contains one row per scheme with:
    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

We store each scheme's NAV as an OHLCV row with source=``amfi``,
symbol = scheme_code (as string), market = ``MF_INDIA``. open=high=low=close=nav.

Volume is 0 (meaningless for MFs).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.indian_mf.amfi_nav")

URL = "https://www.amfiindia.com/spages/NAVAll.txt"


@retry_http(max_attempts=3)
async def _download() -> str:
    # AMFI now 302-redirects NAVAll.txt; httpx does NOT follow redirects by
    # default, so without this the adapter got a tiny redirect page (0 NAV rows)
    # and could hang. With follow_redirects it pulls the full ~1.6MB file in <1s.
    async with get_async_client(headers={"Accept": "text/plain"}) as client:
        r = await client.get(URL, follow_redirects=True, timeout=60.0)
        r.raise_for_status()
        return r.text


async def fetch_amfi_nav() -> list[dict[str, Any]]:
    try:
        txt = await _download()
    except Exception as e:  # noqa: BLE001
        log.warning(f"amfi_nav: download failed: {type(e).__name__}: {e}")
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Scheme Code") or ";" not in line:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        code, _isin_g, _isin_d, name, nav_str, date_str = parts[:6]
        try:
            nav = float(nav_str)
        except ValueError:
            continue
        try:
            d = datetime.strptime(date_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        rows.append(
            {
                "time": d,
                "symbol": f"MF_{code}",
                "market": "MF_INDIA",
                "source": "amfi",
                "timeframe": "1d",
                "open": nav,
                "high": nav,
                "low": nav,
                "close": nav,
                "volume": 0,
            }
        )
    return rows


async def ingest_amfi_nav(session: AsyncSession | None = None) -> int:
    log.info("ingest.amfi_nav starting")
    rows = await fetch_amfi_nav()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.amfi_nav done: {n} rows")
    return n
