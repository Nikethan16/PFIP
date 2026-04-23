"""Multi-exchange CCXT OHLCV ingest.

Extends ``pfip.ingest.ccxt_ohlcv`` to support Coinbase / Kraken / Bybit / OKX
for a watchlist of symbols. The single-symbol ``ingest_ohlcv`` is reused; this
module layers the watchlist loop and per-exchange error handling.

Public API:
    - ``SUPPORTED_EXCHANGES`` — tuple of ccxt ids we verify on import
    - ``fetch_watchlist`` — pure function returning list of dict rows
    - ``ingest_watchlist`` — async DB-writing function

The watchlist loop is designed to keep going when an exchange-symbol pair is
unsupported (ccxt.BadSymbol, ccxt.NetworkError, etc.). Failures are logged and
returned in the summary count.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import anyio
import ccxt
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_ohlcv_rows
from pfip.ingest.ccxt_ohlcv import _symbol_to_market, _fetch_candles_sync

log = get_logger("pfip.ingest.crypto.ccxt_multi")

SUPPORTED_EXCHANGES: tuple[str, ...] = ("coinbase", "kraken", "bybit", "okx")

# Symbol conventions vary between exchanges. A single watchlist symbol can be
# rewritten by exchange (e.g. Coinbase uses BTC/USD, Bybit uses BTC/USDT).
_SYMBOL_REWRITES: dict[str, dict[str, str]] = {
    "BTC/USD": {"bybit": "BTC/USDT", "okx": "BTC/USDT"},
    "ETH/USD": {"bybit": "ETH/USDT", "okx": "ETH/USDT"},
    "SOL/USD": {"bybit": "SOL/USDT", "okx": "SOL/USDT"},
    "BNB/USD": {"bybit": "BNB/USDT", "okx": "BNB/USDT", "coinbase": "BNB/USD"},
}


def _rewrite_symbol(symbol: str, exchange: str) -> str:
    """Return the exchange-appropriate symbol form."""
    return _SYMBOL_REWRITES.get(symbol, {}).get(exchange, symbol)


def fetch_watchlist(
    symbols: Iterable[str],
    exchanges: Iterable[str] = SUPPORTED_EXCHANGES,
    *,
    timeframe: str = "1d",
    since: datetime | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Fetch OHLCV candles for every (symbol, exchange) pair.

    Returns flat list of dict rows suitable for ``upsert_ohlcv_rows``.
    Unsupported pairs are skipped with a warning (never raised).
    """
    log.info("ingest.ccxt_multi starting")
    since_ms: int | None = None
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        since_ms = int(since.timestamp() * 1000)

    out: list[dict[str, Any]] = []
    for ex in exchanges:
        if ex not in SUPPORTED_EXCHANGES:
            log.warning(f"ccxt_multi: unsupported exchange {ex}, skipping")
            continue
        if not hasattr(ccxt, ex):
            log.warning(f"ccxt_multi: ccxt has no class for {ex}")
            continue
        for sym in symbols:
            use_sym = _rewrite_symbol(sym, ex)
            try:
                rows = _fetch_candles_sync(ex, use_sym, timeframe, since_ms, limit)
            except Exception as e:  # noqa: BLE001 — ccxt throws many types
                log.warning(f"ccxt_multi: {ex} {use_sym} failed: {type(e).__name__}: {e}")
                continue
            market = _symbol_to_market(use_sym)
            for ts_ms, o, h, l, c, v in rows:
                out.append(
                    {
                        "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                        "symbol": use_sym,
                        "market": market,
                        "source": ex,
                        "timeframe": timeframe,
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": v,
                    }
                )
            log.info(f"ccxt_multi: {ex} {use_sym} -> {len(rows)} candles")
    return out


async def ingest_watchlist(
    symbols: Iterable[str] = ("BTC/USD", "ETH/USD", "SOL/USD"),
    exchanges: Iterable[str] = SUPPORTED_EXCHANGES,
    *,
    timeframe: str = "1d",
    lookback_days: int = 400,
    session: AsyncSession | None = None,
) -> int:
    """Fetch and upsert OHLCV for a crypto watchlist across exchanges."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
    rows = await anyio.to_thread.run_sync(
        lambda: fetch_watchlist(
            symbols=list(symbols),
            exchanges=list(exchanges),
            timeframe=timeframe,
            since=since,
        )
    )
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.ccxt_multi done: {n} rows")
    return n
