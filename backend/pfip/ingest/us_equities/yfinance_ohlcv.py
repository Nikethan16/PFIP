"""Yahoo Finance daily EOD OHLCV via yfinance.

Fetches adjusted close, splits and dividends for a watchlist of symbols.
Splits and dividends are stored as ``fundamentals`` rows alongside OHLCV.

yfinance is a synchronous library; we run it in a worker thread so the async
event loop is not blocked.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import anyio
import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_fundamentals, upsert_ohlcv_rows

log = get_logger("pfip.ingest.us_equities.yfinance_ohlcv")


def _fetch_symbol_sync(symbol: str, start: datetime, end: datetime) -> dict[str, Any]:
    """Synchronous yfinance call — returns history, splits, dividends frames."""
    t = yf.Ticker(symbol)
    hist = t.history(start=start.date().isoformat(), end=end.date().isoformat(), auto_adjust=False)
    splits = t.splits
    divs = t.dividends
    return {"history": hist, "splits": splits, "dividends": divs}


def fetch_yfinance_ohlcv(
    symbols: Iterable[str],
    *,
    lookback_days: int = 400,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (ohlcv_rows, fundamentals_rows). Pure function — no DB writes."""
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=lookback_days)
    ohlcv_rows: list[dict[str, Any]] = []
    fund_rows: list[dict[str, Any]] = []
    today = date.today()
    for sym in symbols:
        try:
            blob = _fetch_symbol_sync(sym, start, end)
        except Exception as e:  # noqa: BLE001
            log.warning(f"yfinance: {sym} fetch failed: {type(e).__name__}: {e}")
            continue
        hist: pd.DataFrame = blob["history"]
        if hist is None or hist.empty:
            log.warning(f"yfinance: {sym} empty history")
            continue
        for ts, row in hist.iterrows():
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            ohlcv_rows.append(
                {
                    "time": ts.to_pydatetime(),
                    "symbol": sym,
                    "market": "US_EQUITY",
                    "source": "yfinance",
                    "timeframe": "1d",
                    "open": row.get("Open", 0),
                    "high": row.get("High", 0),
                    "low": row.get("Low", 0),
                    "close": row.get("Adj Close", row.get("Close", 0)),
                    "volume": row.get("Volume", 0),
                }
            )
        splits = blob["splits"]
        if splits is not None and len(splits):
            for idx, val in splits.items():
                d = idx.date() if hasattr(idx, "date") else idx
                fund_rows.append(
                    {
                        "as_of_date": today,
                        "report_date": d,
                        "symbol": sym,
                        "field": "split_ratio",
                        "value": float(val),
                        "source": "yfinance",
                    }
                )
        divs = blob["dividends"]
        if divs is not None and len(divs):
            for idx, val in divs.items():
                d = idx.date() if hasattr(idx, "date") else idx
                fund_rows.append(
                    {
                        "as_of_date": today,
                        "report_date": d,
                        "symbol": sym,
                        "field": "dividend_per_share",
                        "value": float(val),
                        "source": "yfinance",
                    }
                )
    return ohlcv_rows, fund_rows


async def ingest_yfinance(
    symbols: Iterable[str] = ("SPY", "QQQ", "DIA", "VTI"),
    *,
    lookback_days: int = 400,
    session: AsyncSession | None = None,
) -> int:
    """Fetch and upsert yfinance data. Returns total OHLCV rows attempted."""
    log.info("ingest.yfinance_ohlcv starting")
    ohlcv_rows, fund_rows = await anyio.to_thread.run_sync(
        lambda: fetch_yfinance_ohlcv(list(symbols), lookback_days=lookback_days)
    )
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, ohlcv_rows)
            await upsert_fundamentals(s, fund_rows)
    else:
        n = await upsert_ohlcv_rows(session, ohlcv_rows)
        await upsert_fundamentals(session, fund_rows)
    log.info(f"ingest.yfinance_ohlcv done: {n} rows")
    return n
