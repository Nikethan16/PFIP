"""Prefect flow: compute technical features from OHLCV into the features table.

Manual run:
    python -m pfip.prefect.flows.compute_features
"""

from __future__ import annotations

import asyncio

import pandas as pd
from prefect import flow, get_run_logger, task
from sqlalchemy import select, text

from pfip.db.session import get_sessionmaker
from pfip.features.technicals import compute_features
from pfip.models.ohlcv import OHLCVRow


@task(name="load-ohlcv")
async def _load_ohlcv(symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(OHLCVRow)
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.source == source,
                OHLCVRow.timeframe == timeframe,
            )
            .order_by(OHLCVRow.time.asc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "time": r.time,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in rows
        ]
    ).set_index("time")


@task(name="write-features")
async def _write_features(features: pd.DataFrame, symbol: str, source: str, timeframe: str) -> int:
    if features.empty:
        return 0
    factory = get_sessionmaker()
    stmt = text("""
        INSERT INTO features (
            time, symbol, source, timeframe,
            rsi_14, macd, macd_signal, macd_hist, atr_14, return_7d, volatility_30d, extras
        )
        VALUES (
            :time, :symbol, :source, :timeframe,
            :rsi_14, :macd, :macd_signal, :macd_hist, :atr_14, :return_7d, :volatility_30d, :extras
        )
        ON CONFLICT (time, symbol, source, timeframe) DO UPDATE SET
            rsi_14 = EXCLUDED.rsi_14,
            macd = EXCLUDED.macd,
            macd_signal = EXCLUDED.macd_signal,
            macd_hist = EXCLUDED.macd_hist,
            atr_14 = EXCLUDED.atr_14,
            return_7d = EXCLUDED.return_7d,
            volatility_30d = EXCLUDED.volatility_30d
        """)
    async with factory() as session:
        for ts, row in features.iterrows():
            params = {
                "time": ts,
                "symbol": symbol,
                "source": source,
                "timeframe": timeframe,
                "rsi_14": None if pd.isna(row["rsi_14"]) else float(row["rsi_14"]),
                "macd": None if pd.isna(row["macd"]) else float(row["macd"]),
                "macd_signal": None if pd.isna(row["macd_signal"]) else float(row["macd_signal"]),
                "macd_hist": None if pd.isna(row["macd_hist"]) else float(row["macd_hist"]),
                "atr_14": None if pd.isna(row["atr_14"]) else float(row["atr_14"]),
                "return_7d": None if pd.isna(row["return_7d"]) else float(row["return_7d"]),
                "volatility_30d": (
                    None if pd.isna(row["volatility_30d"]) else float(row["volatility_30d"])
                ),
                "extras": "{}",
            }
            await session.execute(stmt, params)
        await session.commit()
    return int(features.shape[0])


@flow(name="compute-features", log_prints=True)
async def compute_features_flow(
    symbol: str = "BTC/USD", source: str = "coinbase", timeframe: str = "1d"
) -> int:
    """Load OHLCV, compute features, upsert into features table."""
    log = get_run_logger()
    df = await _load_ohlcv(symbol, source, timeframe)
    if df.empty:
        log.warning(f"No OHLCV data found for {symbol} {source} {timeframe}")
        return 0
    feats = compute_features(df)
    written = await _write_features(feats, symbol, source, timeframe)
    log.info(f"Wrote {written} feature rows for {symbol}")
    return written


if __name__ == "__main__":
    asyncio.run(compute_features_flow())
