"""Prefect flow: train HMM regime detector per market and write today's label.

Schedule: daily. Trains on trailing 3 years of D1 OHLCV and writes a
row to ``regime`` (current label) + a row to ``regime_transitions`` when the
label changes.

    python -m pfip.prefect.flows.regime_detect_daily --symbol BTC/USD
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from prefect import flow, get_run_logger, task
from sqlalchemy import desc, select

from pfip.db.session import get_sessionmaker
from pfip.models.calibration_reports import RegimeTransitionRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.regime import RegimeRow
from pfip.regime.hmm_detector import HMMRegimeDetector


@task(name="load-3y-ohlcv")
async def _load_3y(symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    since = datetime.now(tz=timezone.utc) - timedelta(days=365 * 3)
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
        [{"time": r.time, "close": float(r.close)} for r in rows]
    ).set_index("time")


@task(name="write-regime")
async def _write_regime(symbol: str, regime: str, confidence: float) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        # Read most recent regime for transition detection.
        stmt = (
            select(RegimeRow)
            .where(RegimeRow.symbol == symbol)
            .order_by(desc(RegimeRow.since))
            .limit(1)
        )
        res = await session.execute(stmt)
        prev = res.scalars().first()
        now = datetime.now(tz=timezone.utc)

        row = RegimeRow(
            symbol=symbol, regime=regime, since=now, confidence=float(confidence)
        )
        session.add(row)

        if prev is None or prev.regime != regime:
            session.add(
                RegimeTransitionRow(
                    symbol=symbol,
                    from_regime=prev.regime if prev is not None else None,
                    to_regime=regime,
                    at=now,
                    confidence=float(confidence),
                )
            )
        await session.commit()


@flow(name="regime-detect-daily", log_prints=True)
async def regime_detect_daily_flow(
    symbol: str = "BTC/USD", source: str = "coinbase", timeframe: str = "1d"
) -> dict[str, str]:
    """Fit HMM on trailing 3y, predict current regime, persist."""
    log = get_run_logger()
    df = await _load_3y(symbol, source, timeframe)
    if df.empty or len(df) < 50:
        log.warning(f"Not enough data for {symbol} {source} {timeframe}")
        return {"symbol": symbol, "status": "no-data"}

    returns = np.log(df["close"] / df["close"].shift(1)).dropna()
    detector = HMMRegimeDetector(n_states=4)
    detector.fit(returns)

    # Persist to MLflow (non-blocking on failure)
    try:  # pragma: no cover
        detector.persist_to_mlflow(run_name=f"regime_{symbol}")
    except Exception as exc:  # pragma: no cover
        log.warning(f"MLflow persist failed: {exc}")

    score_df = detector.score_per_bar(df)
    last = score_df.iloc[-1]
    regime_label = str(last["regime"])
    confidence = float(last["confidence"])

    await _write_regime(symbol, regime_label, confidence)
    log.info(f"{symbol}: {regime_label} (conf={confidence:.2f})")
    return {"symbol": symbol, "regime": regime_label, "confidence": f"{confidence:.3f}"}


if __name__ == "__main__":
    asyncio.run(regime_detect_daily_flow())
