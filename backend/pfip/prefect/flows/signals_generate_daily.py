"""Prefect flow: generate Stage-4 signals for a list of assets.

Pipeline per asset:
    1. Load OHLCV + pre-computed features.
    2. Pick current regime (most-recent row in ``regime``).
    3. Route to the matching specialist via the regime router.
    4. Walk-forward train on trailing 3y.
    5. Predict today's row → Signal.
    6. Write into ``signals`` table.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd
from prefect import flow, get_run_logger, task
from sqlalchemy import desc, select

from pfip.core.contracts import Regime, Signal
from pfip.db.session import get_sessionmaker
from pfip.features.technicals import compute_features
from pfip.models.ohlcv import OHLCVRow
from pfip.models.regime import RegimeRow
from pfip.models.signals import SignalRow
from pfip.signals.lgbm_baseline import FEATURE_COLUMNS, make_label
from pfip.signals.regime_router import RegimeRouter


@task(name="load-prices")
async def _load_prices(symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    since = datetime.now(tz=timezone.utc) - timedelta(days=365 * 4)
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(OHLCVRow)
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.source == source,
                OHLCVRow.timeframe == timeframe,
                OHLCVRow.time >= since,
            )
            .order_by(OHLCVRow.time.asc())
        )
        res = await session.execute(stmt)
        rows = res.scalars().all()
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


@task(name="current-regime")
async def _current_regime(symbol: str) -> Regime:
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(RegimeRow)
            .where(RegimeRow.symbol == symbol)
            .order_by(desc(RegimeRow.since))
            .limit(1)
        )
        res = await session.execute(stmt)
        row = res.scalars().first()
    if row is None:
        return Regime.SIDEWAYS
    try:
        return Regime(row.regime)
    except ValueError:
        return Regime.SIDEWAYS


@task(name="write-signal")
async def _write_signal(signal: Signal) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        row = SignalRow(
            asset=signal.asset,
            direction=signal.direction.value,
            confidence=signal.confidence,
            horizon_hours=signal.horizon_hours,
            regime=signal.regime.value,
            model_name=signal.model_name,
            model_version=signal.model_version,
            drivers=[d.model_dump() for d in signal.drivers],
            counter_arguments=[d.model_dump() for d in signal.counter_arguments],
            generated_at=signal.generated_at,
        )
        session.add(row)
        await session.commit()


@flow(name="signals-generate-daily", log_prints=True)
async def signals_generate_daily_flow(
    symbol: str = "BTC/USD",
    source: str = "coinbase",
    timeframe: str = "1d",
) -> dict[str, str]:
    """End-to-end: load bars, compute features, route, fit, predict, persist."""
    log = get_run_logger()
    price_df = await _load_prices(symbol, source, timeframe)
    if price_df.empty or len(price_df) < 200:
        log.warning(f"Not enough OHLCV rows for {symbol}")
        return {"symbol": symbol, "status": "no-data"}

    feats = compute_features(price_df)
    # Keep only plan features
    feats = feats[[c for c in FEATURE_COLUMNS if c in feats.columns]].copy()
    feats = feats.dropna()
    if feats.empty:
        log.warning(f"Features empty after warm-up for {symbol}")
        return {"symbol": symbol, "status": "features-empty"}

    regime = await _current_regime(symbol)
    router = RegimeRouter()
    model = router.get(regime)

    y = make_label(price_df["close"], horizon=model.horizon).reindex(feats.index)
    valid = y.dropna().index
    if len(valid) < 250:
        log.warning(f"Not enough labelled rows for {symbol}")
        return {"symbol": symbol, "status": "not-enough-labels"}

    model.fit(feats.loc[valid], y.loc[valid])

    last_row = feats.iloc[-1]
    signal = model.to_signal(
        asset=symbol,
        feature_row=last_row,
        regime=regime,
        generated_at=datetime.now(tz=timezone.utc),
    )
    await _write_signal(signal)
    log.info(f"{symbol}: wrote signal {signal.direction.value} c={signal.confidence}")
    return {
        "symbol": symbol,
        "direction": signal.direction.value,
        "confidence": str(signal.confidence),
    }


if __name__ == "__main__":
    asyncio.run(signals_generate_daily_flow())
