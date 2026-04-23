"""Reusable DB upsert helpers for ingest adapters.

Each function performs an idempotent insert (``ON CONFLICT DO NOTHING``) against
one of the core tables (ohlcv, news, fundamentals). The OHLCV helper matches the
composite PK (time, symbol, source, timeframe); the news helper matches the
unique URL constraint; fundamentals matches (as_of_date, symbol, field, source).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_ohlcv_rows(
    session: AsyncSession,
    rows: Iterable[dict[str, Any]],
) -> int:
    """Insert OHLCV rows idempotently.

    Each row must have keys: time, symbol, market, source, timeframe, open, high,
    low, close, volume. ``time`` must be a UTC datetime.
    """
    stmt = text(
        """
        INSERT INTO ohlcv (time, symbol, market, source, timeframe, open, high, low, close, volume)
        VALUES (:time, :symbol, :market, :source, :timeframe, :open, :high, :low, :close, :volume)
        ON CONFLICT (time, symbol, source, timeframe) DO NOTHING
        """
    )
    count = 0
    for row in rows:
        t: datetime = row["time"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        await session.execute(
            stmt,
            {
                "time": t,
                "symbol": row["symbol"],
                "market": row["market"],
                "source": row["source"],
                "timeframe": row["timeframe"],
                "open": Decimal(str(row["open"])),
                "high": Decimal(str(row["high"])),
                "low": Decimal(str(row["low"])),
                "close": Decimal(str(row["close"])),
                "volume": Decimal(str(row.get("volume", 0))),
            },
        )
        count += 1
    await session.commit()
    return count


async def upsert_news(
    session: AsyncSession,
    items: Iterable[dict[str, Any]],
) -> int:
    """Insert news rows idempotently via unique URL.

    Each item must have: time, title, url, source. Optional: symbol, sentiment,
    summary. We also accept a ``category`` key and fold it into summary prefix
    if the news table has no category column yet (0002 migration adds it).
    """
    stmt = text(
        """
        INSERT INTO news (time, title, url, source, symbol, sentiment, summary, category)
        VALUES (:time, :title, :url, :source, :symbol, :sentiment, :summary, :category)
        ON CONFLICT (url) DO NOTHING
        """
    )
    count = 0
    for item in items:
        t: datetime = item["time"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        await session.execute(
            stmt,
            {
                "time": t,
                "title": (item["title"] or "")[:2000],
                "url": item["url"],
                "source": item["source"],
                "symbol": item.get("symbol"),
                "sentiment": item.get("sentiment"),
                "summary": item.get("summary"),
                "category": item.get("category", "news"),
            },
        )
        count += 1
    await session.commit()
    return count


async def upsert_fundamentals(
    session: AsyncSession,
    rows: Iterable[dict[str, Any]],
) -> int:
    """Insert fundamentals rows idempotently.

    Each row: as_of_date, report_date, symbol, field, value, source.
    """
    stmt = text(
        """
        INSERT INTO fundamentals (as_of_date, report_date, symbol, field, value, source)
        VALUES (:as_of_date, :report_date, :symbol, :field, :value, :source)
        ON CONFLICT (as_of_date, symbol, field, source) DO NOTHING
        """
    )
    count = 0
    for row in rows:
        value = row.get("value")
        if value is not None and not isinstance(value, Decimal):
            try:
                value = Decimal(str(value))
            except Exception:
                value = None
        await session.execute(
            stmt,
            {
                "as_of_date": row["as_of_date"]
                if isinstance(row["as_of_date"], date)
                else date.fromisoformat(str(row["as_of_date"])),
                "report_date": row["report_date"]
                if isinstance(row["report_date"], date)
                else date.fromisoformat(str(row["report_date"])),
                "symbol": row["symbol"],
                "field": row["field"],
                "value": value,
                "source": row["source"],
            },
        )
        count += 1
    await session.commit()
    return count
