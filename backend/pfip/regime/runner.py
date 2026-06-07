"""Regime runner: fit HMM per market, write the latest label to ``regime``.

Used by the Prefect flow ``regime_detect_daily``. Designed to be a single
function (``run_for_symbol``) so it can also be invoked ad-hoc from the API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import desc, select

from pfip.core.contracts import Regime
from pfip.db.sources import resolve_ohlcv_source
from pfip.regime.hmm import HMMRegimeDetector, build_three_state

log = logging.getLogger(__name__)


@dataclass
class RegimeRunResult:
    """Outcome of a regime-run for one symbol."""

    symbol: str
    regime: Regime
    confidence: float
    state_means: dict[int, float]
    n_obs: int
    status: str = "ok"


async def _load_3y_close(session, symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    try:
        from pfip.models.ohlcv import OHLCVRow
    except Exception:
        return pd.DataFrame()

    since = datetime.now(tz=timezone.utc) - timedelta(days=365 * 3)
    stmt = (
        select(OHLCVRow.time, OHLCVRow.close)
        .where(
            OHLCVRow.symbol == symbol,
            OHLCVRow.source == source,
            OHLCVRow.timeframe == timeframe,
            OHLCVRow.time >= since,
        )
        .order_by(OHLCVRow.time.asc())
    )
    res = await session.execute(stmt)
    rows = res.all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "close"])
    df["close"] = df["close"].astype(float)
    return df.set_index("time")


async def _persist_regime(session, symbol: str, regime: Regime, confidence: float) -> None:
    from pfip.models.regime import RegimeRow

    now = datetime.now(tz=timezone.utc)
    row = RegimeRow(symbol=symbol, regime=regime.value, since=now, confidence=float(confidence))
    session.add(row)

    # If the regime changed, log a transition row.
    try:
        from pfip.models.calibration_reports import RegimeTransitionRow

        prev_stmt = (
            select(RegimeRow)
            .where(RegimeRow.symbol == symbol)
            .order_by(desc(RegimeRow.since))
            .offset(1)  # the row we just added is at offset 0 once flushed
            .limit(1)
        )
        await session.flush()
        res = await session.execute(prev_stmt)
        prev = res.scalars().first()
        if prev is None or prev.regime != regime.value:
            session.add(
                RegimeTransitionRow(
                    symbol=symbol,
                    from_regime=prev.regime if prev is not None else None,
                    to_regime=regime.value,
                    at=now,
                    confidence=float(confidence),
                )
            )
    except Exception as exc:  # pragma: no cover — table may be absent in tests
        log.debug("regime transition logging skipped: %s", exc)

    await session.commit()


async def run_for_symbol(
    session,
    symbol: str,
    *,
    source: str = "coinbase",
    timeframe: str = "1d",
    n_states: int = 3,
    persist_mlflow: bool = True,
) -> RegimeRunResult:
    """Fit + predict + persist regime for a single symbol."""
    df = await _load_3y_close(session, symbol, source, timeframe)
    if df.empty or len(df) < 60:
        return RegimeRunResult(
            symbol=symbol,
            regime=Regime.SIDEWAYS,
            confidence=0.0,
            state_means={},
            n_obs=len(df),
            status="no-data",
        )

    returns = np.log(df["close"] / df["close"].shift(1)).dropna()
    detector = build_three_state() if n_states == 3 else HMMRegimeDetector(n_states=n_states)
    try:
        detector.fit(returns)
    except Exception as exc:
        log.warning("HMM fit failed for %s: %s", symbol, exc)
        return RegimeRunResult(
            symbol=symbol,
            regime=Regime.SIDEWAYS,
            confidence=0.0,
            state_means={},
            n_obs=len(returns),
            status="fit-failed",
        )

    if persist_mlflow:
        try:  # pragma: no cover — only when mlflow is installed
            detector.persist_to_mlflow(run_name=f"regime_{symbol.replace('/', '_')}")
        except Exception:
            pass

    score = detector.score_per_bar(df)
    last = score.iloc[-1]
    regime_value = str(last["regime"])
    confidence = float(last["confidence"])
    try:
        regime = Regime(regime_value)
    except ValueError:
        regime = Regime.SIDEWAYS

    await _persist_regime(session, symbol, regime, confidence)

    return RegimeRunResult(
        symbol=symbol,
        regime=regime,
        confidence=confidence,
        state_means={s: stats["mean"] for s, stats in detector._state_stats.items()},
        n_obs=len(returns),
        status="ok",
    )


async def run_for_watchlist(
    session, timeframe: str = "1d", n_states: int = 3
) -> list[RegimeRunResult]:
    """Run the regime fit for every entry in ``watchlist``."""
    try:
        from pfip.models.watchlist import WatchlistRow

        res = await session.execute(select(WatchlistRow))
        rows = list(res.scalars().all())
    except Exception as exc:  # pragma: no cover
        log.warning("watchlist load failed: %s", exc)
        return []

    out: list[RegimeRunResult] = []
    for r in rows:
        symbol = str(r.symbol)
        # Read from the source that ACTUALLY ingested this symbol (US equities
        # live under 'tiingo', not the heuristic's 'yfinance'); fall back to the
        # heuristic only when no OHLCV rows exist yet.
        source = await resolve_ohlcv_source(session, symbol, timeframe) or _source_for(symbol)
        try:
            result = await run_for_symbol(
                session,
                symbol=symbol,
                source=source,
                timeframe=timeframe,
                n_states=n_states,
            )
        except Exception as exc:  # pragma: no cover
            log.warning("regime run failed for %s: %s", symbol, exc)
            continue
        out.append(result)
    return out


def _source_for(symbol: str) -> str:
    s = symbol.upper()
    if "/" in s or s.endswith("USD") or s.endswith("USDT"):
        return "coinbase"
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return "jugaad"
    if symbol.endswith("=X"):
        return "frankfurter"
    return "yfinance"
