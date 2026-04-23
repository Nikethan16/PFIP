"""Stooq EOD OHLCV — CSV endpoint (no API key).

Endpoint shape: https://stooq.com/q/d/l/?s={symbol}&i=d  (daily)
We add ``.us`` suffix for US tickers per Stooq convention (e.g. ``aapl.us``).

Used as a fallback when yfinance rate-limits or fails.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.us_equities.stooq_ohlcv")

BASE = "https://stooq.com/q/d/l/"


def _stooq_symbol(sym: str) -> str:
    """Map a US ticker to Stooq convention."""
    s = sym.lower()
    if "." in s:
        return s
    return f"{s}.us"


@retry_http(max_attempts=3)
async def _fetch_csv(sym: str) -> str:
    async with get_async_client(headers={"Accept": "text/csv"}) as client:
        r = await client.get(BASE, params={"s": _stooq_symbol(sym), "i": "d"})
        r.raise_for_status()
        return r.text


async def fetch_stooq(symbols: Iterable[str]) -> list[dict[str, Any]]:
    """Return OHLCV rows for each symbol from Stooq daily CSV."""
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            csv = await _fetch_csv(sym)
        except Exception as e:  # noqa: BLE001
            log.warning(f"stooq: {sym} fetch failed: {type(e).__name__}: {e}")
            continue
        if "Date,Open" not in csv:
            log.warning(f"stooq: {sym} unexpected payload")
            continue
        df = pd.read_csv(io.StringIO(csv))
        for _, row in df.iterrows():
            try:
                d = datetime.fromisoformat(str(row["Date"]))
            except Exception:
                continue
            rows.append(
                {
                    "time": d.replace(tzinfo=timezone.utc),
                    "symbol": sym.upper(),
                    "market": "US_EQUITY",
                    "source": "stooq",
                    "timeframe": "1d",
                    "open": row.get("Open", 0),
                    "high": row.get("High", 0),
                    "low": row.get("Low", 0),
                    "close": row.get("Close", 0),
                    "volume": row.get("Volume", 0) or 0,
                }
            )
    return rows


async def ingest_stooq(
    symbols: Iterable[str] = ("SPY", "QQQ", "DIA"),
    session: AsyncSession | None = None,
) -> int:
    """Fetch Stooq OHLCV and upsert."""
    log.info("ingest.stooq_ohlcv starting")
    rows = await fetch_stooq(list(symbols))
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.stooq_ohlcv done: {n} rows")
    return n
