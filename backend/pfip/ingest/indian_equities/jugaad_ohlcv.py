"""NSE EOD OHLCV via jugaad-data.

jugaad-data is an unofficial, well-maintained Python client for NSE historical
data. It is synchronous so we run it in a worker thread. Delisted symbols
raise — we swallow and log.

Install: ``pip install jugaad-data`` (not pinned in pyproject to keep core
install lean; Prefect flow will attempt import and warn if missing).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.indian_equities.jugaad_ohlcv")


def _fetch_symbol_sync(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """Synchronous per-symbol fetch using jugaad_data.nse.stock_df."""
    try:
        from jugaad_data.nse import stock_df  # type: ignore
    except ImportError:
        log.warning("jugaad-data not installed; skipping NSE EOD")
        return []
    try:
        df = stock_df(symbol=symbol, from_date=start, to_date=end, series="EQ")
    except Exception as e:  # noqa: BLE001
        log.warning(f"jugaad: {symbol} failed (may be delisted): {type(e).__name__}: {e}")
        return []
    rows: list[dict[str, Any]] = []
    if df is None or df.empty:
        return rows
    for _, r in df.iterrows():
        d = r.get("DATE") if "DATE" in df.columns else r.get("Date")
        if d is None:
            continue
        try:
            t = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        rows.append(
            {
                "time": t,
                "symbol": f"{symbol}.NS",
                "market": "NSE",
                "source": "jugaad",
                "timeframe": "1d",
                "open": r.get("OPEN", r.get("Open", 0)),
                "high": r.get("HIGH", r.get("High", 0)),
                "low": r.get("LOW", r.get("Low", 0)),
                "close": r.get("CLOSE", r.get("Close", 0)),
                "volume": r.get("VOLUME", r.get("Volume", 0)) or 0,
            }
        )
    return rows


def fetch_jugaad(symbols: Iterable[str], *, lookback_days: int = 400) -> list[dict[str, Any]]:
    """Pure function: fetch NSE EOD per symbol, return flat list of rows."""
    end = date.today()
    start = end - timedelta(days=lookback_days)
    out: list[dict[str, Any]] = []
    for sym in symbols:
        # jugaad expects bare symbol like "RELIANCE" (no .NS suffix)
        bare = sym.replace(".NS", "").upper()
        rows = _fetch_symbol_sync(bare, start, end)
        out.extend(rows)
        log.info(f"jugaad: {bare} -> {len(rows)} rows")
    return out


async def ingest_jugaad(
    symbols: Iterable[str] = ("RELIANCE", "TCS", "HDFCBANK", "INFY"),
    *,
    lookback_days: int = 400,
    session: AsyncSession | None = None,
) -> int:
    """Fetch jugaad NSE EOD and upsert."""
    log.info("ingest.jugaad_ohlcv starting")
    rows = await anyio.to_thread.run_sync(
        lambda: fetch_jugaad(list(symbols), lookback_days=lookback_days)
    )
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.jugaad_ohlcv done: {n} rows")
    return n
