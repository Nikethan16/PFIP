"""Alpha Vantage EOD OHLCV — the reliable US fallback from a datacenter IP.

Why this exists
---------------
Tiingo (keyed) silently returns 0 rows once its free monthly quota is spent, and
both yfinance and stooq are rate-limited from the VM's datacenter IP. Alpha
Vantage, however, IS reachable from the VM (the Deep Research path already proves
it). AV's free tier is only ~25 calls/day, so this adapter is meant to be used
as a **gap-filler**: fetch ONLY the US symbols whose latest stored bar is stale,
capped to a small budget, rather than the whole universe every night.

``TIME_SERIES_DAILY`` (``outputsize=compact`` = last 100 bars) is keyed and
returns adjusted-unaware EOD OHLCV — enough to keep a daily chart current.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.us_equities.alphavantage_ohlcv")

_BASE = "https://www.alphavantage.co/query"


def _av_key() -> str:
    """AV key, tolerating both env-var spellings (see research.fundamentals)."""
    return (
        os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY") or ""
    ).strip()


@retry_http(max_attempts=2)
async def _fetch_daily(symbol: str, key: str) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(
            _BASE,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": key,
            },
        )
        r.raise_for_status()
        return r.json() or {}


async def fetch_alphavantage_daily(symbols: Iterable[str]) -> list[dict[str, Any]]:
    """OHLCV rows for each symbol via AV TIME_SERIES_DAILY. Empty on no-key/limit."""
    key = _av_key()
    if not key:
        log.warning("alphavantage_ohlcv: no key, no-op")
        return []
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            data = await _fetch_daily(sym.upper(), key)
        except Exception as e:  # noqa: BLE001
            log.warning(f"av_ohlcv: {sym} failed: {type(e).__name__}: {e}")
            continue
        series = data.get("Time Series (Daily)")
        if not series:
            # {"Note"/"Information": ...} == rate-limited; stop to save the budget.
            if data.get("Note") or data.get("Information"):
                log.warning("av_ohlcv: rate-limited; stopping this run")
                break
            continue
        for ds, bar in series.items():
            try:
                d = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            rows.append(
                {
                    "time": d,
                    "symbol": sym.upper(),
                    "market": "US_EQUITY",
                    "source": "alphavantage",
                    "timeframe": "1d",
                    "open": float(bar.get("1. open", 0) or 0),
                    "high": float(bar.get("2. high", 0) or 0),
                    "low": float(bar.get("3. low", 0) or 0),
                    "close": float(bar.get("4. close", 0) or 0),
                    "volume": float(bar.get("5. volume", 0) or 0),
                }
            )
    return rows


async def ingest_alphavantage_daily(
    symbols: Iterable[str] = (), session: AsyncSession | None = None
) -> int:
    """Fetch AV daily OHLCV for ``symbols`` and upsert. No-op on empty input."""
    symbols = [s for s in symbols if s]
    if not symbols:
        return 0
    log.info(f"ingest.alphavantage_ohlcv starting ({len(symbols)} symbols)")
    rows = await fetch_alphavantage_daily(symbols)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.alphavantage_ohlcv done: {n} rows")
    return n


__all__ = ["fetch_alphavantage_daily", "ingest_alphavantage_daily"]
