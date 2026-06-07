"""Prefect flow: train HMM regime detector per watchlist symbol, write today's label.

Schedule: daily. For every watchlist symbol it resolves the symbol's real OHLCV
``source`` from the DB (US equities live under ``tiingo``, not the heuristic
``yfinance``), trains on the trailing 3 years of D1 OHLCV, and writes a row to
``regime`` (current label) + a row to ``regime_transitions`` when the label
changes.

    # all watchlist symbols (scheduled / default):
    python -m pfip.prefect.flows.regime_detect_daily
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from prefect import flow, get_run_logger, task
from sqlalchemy import desc, select

from pfip.db.session import get_sessionmaker
from pfip.db.sources import resolve_ohlcv_source
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
    return pd.DataFrame([{"time": r.time, "close": float(r.close)} for r in rows]).set_index("time")


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

        row = RegimeRow(symbol=symbol, regime=regime, since=now, confidence=float(confidence))
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


async def _resolve_source(symbol: str, timeframe: str) -> str | None:
    """The source that actually ingested this symbol's data (not a guess).

    Opens its own session (this flow uses a session-per-operation pattern) and
    delegates the actual query to :func:`pfip.db.sources.resolve_ohlcv_source`.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        return await resolve_ohlcv_source(session, symbol, timeframe)


async def _detect_one(symbol: str, source: str, timeframe: str, log) -> dict[str, str]:
    """Fit HMM on trailing 3y for one symbol, predict + persist the regime."""
    df = await _load_3y(symbol, source, timeframe)
    if df.empty or len(df) < 50:
        log.warning(f"Not enough data for {symbol} {source} {timeframe}")
        return {"symbol": symbol, "status": "no-data"}

    returns = np.log(df["close"] / df["close"].shift(1)).dropna()
    detector = HMMRegimeDetector(n_states=4)
    detector.fit(returns)
    try:  # pragma: no cover — MLflow is best-effort
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


@flow(name="regime-detect-daily", log_prints=True)
async def regime_detect_daily_flow(
    symbol: str | None = None, source: str | None = None, timeframe: str = "1d"
) -> dict:
    """Detect the regime for every watchlist symbol (or a single one if given).

    Default (scheduled) mode iterates the watchlist and resolves each symbol's
    REAL source from the OHLCV table — previously it only ever ran BTC/USD.
    """
    log = get_run_logger()
    if symbol:  # single-symbol / manual mode
        return await _detect_one(symbol, source or "coinbase", timeframe, log)

    factory = get_sessionmaker()
    async with factory() as session:
        from pfip.models.watchlist import WatchlistRow

        symbols = [
            str(r.symbol) for r in (await session.execute(select(WatchlistRow))).scalars().all()
        ]

    results: list[dict[str, str]] = []
    for sym in symbols:
        src = await _resolve_source(sym, timeframe)
        if not src:
            log.warning(f"no OHLCV source for {sym}; skipping")
            results.append({"symbol": sym, "status": "no-data"})
            continue
        try:
            results.append(await _detect_one(sym, src, timeframe, log))
        except Exception as exc:
            log.warning(f"regime failed for {sym}: {exc}")
            results.append({"symbol": sym, "status": "error"})
    log.info(f"regime-detect-daily: processed {len(results)} watchlist symbols")
    return {"n": len(results), "results": results}


if __name__ == "__main__":
    asyncio.run(regime_detect_daily_flow())
