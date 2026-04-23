"""Tiingo EOD OHLCV.

Requires ``TIINGO_API_KEY``. Free tier: 500 calls/hour, 1000 symbols/month.
https://www.tiingo.com/documentation/end-of-day

Without a key the adapter logs a warning and no-ops.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.us_equities.tiingo_ohlcv")

BASE = "https://api.tiingo.com/tiingo/daily"


@retry_http(max_attempts=3)
async def _fetch_symbol(symbol: str, start: str, token: str) -> list[dict[str, Any]]:
    async with get_async_client(
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"}
    ) as client:
        r = await client.get(f"{BASE}/{symbol}/prices", params={"startDate": start})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []


async def fetch_tiingo(
    symbols: Iterable[str],
    *,
    lookback_days: int = 400,
) -> list[dict[str, Any]]:
    """Fetch Tiingo EOD prices for each symbol."""
    token = os.environ.get("TIINGO_API_KEY", "").strip()
    if not token:
        log.warning("TIINGO_API_KEY not set, tiingo ingest no-op")
        return []
    start = (datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            data = await _fetch_symbol(sym, start, token)
        except Exception as e:  # noqa: BLE001
            log.warning(f"tiingo: {sym} failed: {type(e).__name__}: {e}")
            continue
        for bar in data:
            ts = bar.get("date")
            if not ts:
                continue
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            rows.append(
                {
                    "time": t,
                    "symbol": sym.upper(),
                    "market": "US_EQUITY",
                    "source": "tiingo",
                    "timeframe": "1d",
                    "open": bar.get("adjOpen", bar.get("open", 0)),
                    "high": bar.get("adjHigh", bar.get("high", 0)),
                    "low": bar.get("adjLow", bar.get("low", 0)),
                    "close": bar.get("adjClose", bar.get("close", 0)),
                    "volume": bar.get("adjVolume", bar.get("volume", 0)) or 0,
                }
            )
    return rows


async def ingest_tiingo(
    symbols: Iterable[str] = ("SPY", "AAPL", "MSFT"),
    session: AsyncSession | None = None,
) -> int:
    """Fetch Tiingo and upsert."""
    log.info("ingest.tiingo_ohlcv starting")
    rows = await fetch_tiingo(list(symbols))
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.tiingo_ohlcv done: {n} rows")
    return n
