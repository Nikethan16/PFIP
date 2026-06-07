"""NSE full EOD bhavcopy parser.

Downloads the daily CM bhavcopy CSV. The canonical URL pattern changed in 2024
to ``archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv``.
We fall back to the older ``cm{DDMMMYYYY}bhav.csv.zip`` path if the primary
URL is not available.

Rate-limit: NSE blocks fast bots. We use a 2-second polite delay and a
browser-like User-Agent.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.indian_equities.nse_bhavcopy")

_POLITE_DELAY_SEC = 2.0


def _primary_url(d: date) -> str:
    return (
        "https://archives.nseindia.com/products/content/"
        f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
    )


def _legacy_url(d: date) -> str:
    return (
        "https://archives.nseindia.com/content/historical/EQUITIES/"
        f"{d.strftime('%Y')}/{d.strftime('%b').upper()}/"
        f"cm{d.strftime('%d%b%Y').upper()}bhav.csv.zip"
    )


@retry_http(max_attempts=3)
async def _download(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Accept": "text/csv,application/zip,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    async with get_async_client(headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def fetch_bhavcopy(d: date | None = None) -> list[dict[str, Any]]:
    """Download and parse a single day's bhavcopy into OHLCV rows."""
    d = d or (date.today() - timedelta(days=1))
    # Try primary CSV first.
    content: bytes | None = None
    for url in (_primary_url(d), _legacy_url(d)):
        try:
            content = await _download(url)
            log.info(f"nse_bhavcopy: downloaded {url} ({len(content)} bytes)")
            break
        except Exception as e:  # noqa: BLE001
            log.warning(f"nse_bhavcopy: {url} failed: {type(e).__name__}")
            await asyncio.sleep(_POLITE_DELAY_SEC)
    if not content:
        return []

    if content[:2] == b"PK":  # zip
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                df = pd.read_csv(f)
    else:
        df = pd.read_csv(io.BytesIO(content))

    # Normalize column names — the two formats differ.
    df.columns = [c.strip().upper() for c in df.columns]
    sym_col = "SYMBOL"
    if "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        sym = r.get(sym_col)
        if not isinstance(sym, str) or not sym.strip():
            continue
        t = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
        rows.append(
            {
                "time": t,
                "symbol": f"{sym.strip()}.NS",
                "market": "NSE",
                "source": "nse_bhavcopy",
                "timeframe": "1d",
                "open": r.get("OPEN", r.get("OPEN_PRICE", 0)),
                "high": r.get("HIGH", r.get("HIGH_PRICE", 0)),
                "low": r.get("LOW", r.get("LOW_PRICE", 0)),
                "close": r.get("CLOSE", r.get("CLOSE_PRICE", 0)),
                "volume": r.get("TOTTRDQTY", r.get("TTL_TRD_QNTY", 0)) or 0,
            }
        )
    return rows


async def ingest_nse_bhavcopy(d: date | None = None, session: AsyncSession | None = None) -> int:
    """Ingest one day's NSE bhavcopy. Defaults to yesterday."""
    log.info("ingest.nse_bhavcopy starting")
    rows = await fetch_bhavcopy(d)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.nse_bhavcopy done: {n} rows")
    return n
