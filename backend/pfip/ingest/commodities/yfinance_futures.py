"""Commodity futures via yfinance — GC=F (gold), SI=F (silver), CL=F (WTI),
BZ=F (Brent), NG=F (nat-gas), HG=F (copper).
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.ingest.us_equities.yfinance_ohlcv import ingest_yfinance

log = get_logger("pfip.ingest.commodities.yfinance_futures")

COMMODITY_SYMBOLS: tuple[str, ...] = ("GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F")


async def ingest_commodities(
    symbols: Iterable[str] = COMMODITY_SYMBOLS,
    *,
    lookback_days: int = 400,
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.commodities_futures starting")
    n = await ingest_yfinance(symbols=symbols, lookback_days=lookback_days, session=session)
    log.info(f"ingest.commodities_futures done: {n} rows")
    return n
