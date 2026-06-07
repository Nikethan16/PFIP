"""CCXT-backed OHLCV ingest.

One function, ``ingest_ohlcv``, that fetches daily candles from the requested
exchange and upserts them idempotently into the ``ohlcv`` hypertable.

Idempotency: we use ``INSERT ... ON CONFLICT DO NOTHING`` on the composite PK
``(time, symbol, source, timeframe)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import ccxt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.contracts import to_canonical_symbol
from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker

log = get_logger("pfip.ingest.ccxt_ohlcv")


# Map ccxt-native timeframe strings to our canonical timeframe enum values.
_TIMEFRAME_ALIASES = {"1d": "1d", "1h": "1h", "5m": "5m", "1m": "1m"}


def _symbol_to_market(symbol: str) -> str:
    """Map ccxt symbol e.g. BTC/USD -> market label BTC_USD."""
    return symbol.replace("/", "_").replace("-", "_").upper()


def _fetch_candles_sync(
    exchange_id: str, symbol: str, timeframe: str, since_ms: int | None, limit: int
) -> list[list[Any]]:
    """Synchronous ccxt call (ccxt-async is flaky; we run the sync one in a worker)."""
    exchange_cls = getattr(ccxt, exchange_id)
    exchange = exchange_cls({"enableRateLimit": True})
    return exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)


async def _upsert_rows(
    session: AsyncSession,
    *,
    symbol: str,
    market: str,
    source: str,
    timeframe: str,
    rows: list[list[Any]],
) -> int:
    """Insert ccxt rows idempotently. Returns count attempted (conflicts silently skipped)."""
    if not rows:
        return 0
    stmt = text(
        """
        INSERT INTO ohlcv (time, symbol, market, source, timeframe, open, high, low, close, volume)
        VALUES (:time, :symbol, :market, :source, :timeframe, :open, :high, :low, :close, :volume)
        ON CONFLICT (time, symbol, source, timeframe) DO NOTHING
        """
    )
    for ts_ms, o, h, l, c, v in rows:
        await session.execute(
            stmt,
            {
                "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                "symbol": symbol,
                "market": market,
                "source": source,
                "timeframe": timeframe,
                "open": Decimal(str(o)),
                "high": Decimal(str(h)),
                "low": Decimal(str(l)),
                "close": Decimal(str(c)),
                "volume": Decimal(str(v)),
            },
        )
    await session.commit()
    return len(rows)


async def ingest_ohlcv(
    exchange: str = "coinbase",
    symbol: str = "BTC/USD",
    timeframe: str = "1d",
    since: datetime | None = None,
    limit: int = 1000,
) -> int:
    """Fetch OHLCV via ccxt and upsert into the DB. Returns number of candles fetched.

    Args:
        exchange: ccxt exchange id (e.g. ``"coinbase"``).
        symbol: ccxt-formatted symbol (e.g. ``"BTC/USD"``).
        timeframe: one of ``"1m"``, ``"5m"``, ``"1h"``, ``"1d"``.
        since: optional UTC datetime to fetch from. None = exchange default.
        limit: max candles per call.
    """
    if timeframe not in _TIMEFRAME_ALIASES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    since_ms: int | None = None
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        since_ms = int(since.timestamp() * 1000)

    # ccxt is synchronous; run in a thread so we don't block the event loop.
    import anyio

    log.info(f"Fetching {symbol} {timeframe} from {exchange} (since={since}, limit={limit})")
    rows: list[list[Any]] = await anyio.to_thread.run_sync(
        _fetch_candles_sync, exchange, symbol, timeframe, since_ms, limit
    )
    log.info(f"Fetched {len(rows)} candles")

    market = _symbol_to_market(symbol)
    # Persist the symbol in PFIP canonical dash form (BTC-USD), not the ccxt
    # slash form (BTC/USD) used for the fetch call above.
    canonical_symbol = to_canonical_symbol(symbol)
    factory = get_sessionmaker()
    async with factory() as session:
        inserted = await _upsert_rows(
            session,
            symbol=canonical_symbol,
            market=market,
            source=exchange,
            timeframe=timeframe,
            rows=rows,
        )
    log.info(f"Upserted {inserted} rows (conflicts ignored)")
    return inserted
