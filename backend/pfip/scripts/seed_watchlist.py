"""Seed a sensible default watchlist for someone bootstrapping PFIP.

Run inside the backend container:

    docker exec pfip-backend python -m pfip.scripts.seed_watchlist

Idempotent — if a (symbol, market) tuple already exists, the upsert leaves it
alone. Safe to re-run.

Curates 5 tickers per market across crypto majors, US megacaps + indices, and
Indian large-caps. Tweak the lists below or edit the watchlist via the UI
afterwards.
"""

from __future__ import annotations

import asyncio
import sys

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from pfip.db.session import get_sessionmaker
from pfip.models.watchlist import WatchlistRow

CRYPTO = [
    ("BTC-USD", "Bitcoin"),
    ("ETH-USD", "Ethereum"),
    ("SOL-USD", "Solana"),
    ("BNB-USD", "BNB"),
    ("XRP-USD", "XRP"),
]

US_EQUITIES = [
    ("SPY", "S&P 500 ETF"),
    ("QQQ", "Nasdaq-100 ETF"),
    ("AAPL", "Apple"),
    ("NVDA", "NVIDIA"),
    ("MSFT", "Microsoft"),
]

INDIA_EQUITIES = [
    # OHLCV is stored with the NSE ``.NS`` suffix (jugaad writes ``f"{symbol}.NS"``),
    # and the source/market heuristics key off that suffix. The watchlist must carry
    # it too — a bare "INFY" misses resolve_ohlcv_source and is misread as a US
    # ticker, so features/regime compute nothing for it.
    ("RELIANCE.NS", "Reliance Industries"),
    ("TCS.NS", "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("INFY.NS", "Infosys"),
    ("ICICIBANK.NS", "ICICI Bank"),
]

INDIAN_MFS = [
    # Use AMFI scheme codes when known; symbol left readable until lookup.
    ("PPFAS_FLEXI", "Parag Parikh Flexi Cap (DIRECT)"),
    ("MIRAE_LARGE_MID", "Mirae Asset Large & Midcap (DIRECT)"),
    ("QUANT_SMALL", "Quant Small Cap (DIRECT)"),
    ("AXIS_BLUECHIP", "Axis Bluechip (DIRECT)"),
    ("NIPPON_INDEX_500", "Nippon India Index Nifty 500 (DIRECT)"),
]

FX = [
    ("USD-INR", "USD/INR"),
    ("EUR-USD", "EUR/USD"),
    ("GBP-USD", "GBP/USD"),
]


async def _upsert_watchlist() -> int:
    """Idempotent upsert over the curated list. Returns the number of new rows."""
    factory = get_sessionmaker()
    added = 0
    async with factory() as session:
        # One-time cleanup: an earlier seed used bare NSE names ("INFY") that don't
        # match the ".NS"-suffixed OHLCV, so they computed no features/regime. Drop
        # any india_equity row missing the .NS/.BO suffix; the canonical entries
        # below re-add them in the correct form. Idempotent (0 rows after first run).
        stale = await session.execute(
            delete(WatchlistRow).where(
                WatchlistRow.market == "india_equity",
                ~WatchlistRow.symbol.like("%.NS"),
                ~WatchlistRow.symbol.like("%.BO"),
            )
        )
        await session.commit()
        if stale.rowcount:
            logger.info(f"  - removed {stale.rowcount} stale bare india_equity row(s)")

        for market, items in (
            ("crypto", CRYPTO),
            ("us_equity", US_EQUITIES),
            ("india_equity", INDIA_EQUITIES),
            ("india_mf", INDIAN_MFS),
            ("fx", FX),
        ):
            for symbol, note in items:
                # Skip if already present (idempotent re-runs).
                exists = await session.execute(
                    select(WatchlistRow.id).where(
                        WatchlistRow.symbol == symbol,
                        WatchlistRow.market == market,
                    )
                )
                if exists.scalar_one_or_none() is not None:
                    continue
                row = WatchlistRow(symbol=symbol, market=market, note=note)
                session.add(row)
                try:
                    await session.commit()
                    added += 1
                    logger.info(f"  + {market}/{symbol} — {note}")
                except IntegrityError:
                    await session.rollback()
    return added


def main() -> int:
    logger.info("Seeding watchlist with sensible defaults…")
    try:
        added = asyncio.run(_upsert_watchlist())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Seed failed: {type(exc).__name__}: {exc}")
        return 1
    if added == 0:
        logger.info("All entries already present. Nothing to do.")
    else:
        logger.info(f"Added {added} new watchlist row(s).")
    logger.info("Tweak via the Watchlist page in the UI any time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
