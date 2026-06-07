"""Alias re-export of :mod:`pfip.ingest.crypto.ccxt_multi`.

The spec in FEATURES.md M1 calls this module ``ccxt_multi_ohlcv``; the
historical implementation lives at ``ccxt_multi``. We re-export so both names
resolve to the same callables.
"""

from __future__ import annotations

from pfip.ingest.crypto.ccxt_multi import (  # noqa: F401
    SUPPORTED_EXCHANGES,
    fetch_watchlist,
    ingest_watchlist,
)

__all__ = ["SUPPORTED_EXCHANGES", "fetch_watchlist", "ingest_watchlist"]


if __name__ == "__main__":
    import asyncio

    asyncio.run(
        ingest_watchlist(symbols=("BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD"), timeframe="1h")
    )
