"""Signals runner: per watchlist asset, build a fresh ``Signal`` and persist.

Architectural rule (CONTRACTS.md + LLM_ROUTING.md): no LLM ever generates a
``Signal``. The flow here is pure statistics / ML:

    OHLCV -> technicals -> walk-forward fit -> isotonic calibration ->
        confidence -> SignalDirection + drivers -> SignalRow

Confidence below the model's ``confidence_floor`` (65 by default) forces
``HOLD``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select

from pfip.core.contracts import Driver, Regime, Signal, SignalDirection
from pfip.features.technicals import compute_features
from pfip.signals.lgbm_baseline import FEATURE_COLUMNS, LGBMBaselineModel, make_label
from pfip.signals.regime_router import RegimeRouter

log = logging.getLogger(__name__)


@dataclass
class SignalRunResult:
    symbol: str
    direction: SignalDirection
    confidence: int
    regime: Regime
    status: str = "ok"
    signal: Signal | None = None


# ---------------------------------------------------------------------------
# Calibration: turn raw model proba into a calibrated probability via isotonic
# (or Platt) regression. Uses sklearn when available, otherwise no-ops.
# ---------------------------------------------------------------------------


def _calibrate_probabilities(
    raw_probs: np.ndarray, y_true: np.ndarray, method: str = "isotonic"
) -> tuple[np.ndarray, Any | None]:
    """Fit a calibration curve on (raw, y) and return (calibrated, fitted_model).

    Returns ``(raw_probs, None)`` if sklearn isn't available.
    """
    try:  # pragma: no cover — sklearn is in requirements but optional in tests
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression
    except Exception:
        return raw_probs, None

    mask = ~np.isnan(y_true)
    if mask.sum() < 30:
        return raw_probs, None
    r = raw_probs[mask].astype(float)
    y = y_true[mask].astype(float)
    if method == "platt":
        clf = LogisticRegression(max_iter=200)
        clf.fit(r.reshape(-1, 1), y)
        calibrated = clf.predict_proba(raw_probs.reshape(-1, 1))[:, 1]
        return calibrated, clf
    # Default: isotonic.
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(r, y)
    calibrated = iso.transform(np.clip(raw_probs, 0.0, 1.0))
    return calibrated, iso


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_recent_ohlcv(
    session, symbol: str, source: str, timeframe: str, days: int = 365 * 3
) -> pd.DataFrame:
    try:
        from pfip.models.ohlcv import OHLCVRow
    except Exception:
        return pd.DataFrame()
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
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


async def _current_regime(session, symbol: str) -> Regime:
    try:
        from pfip.models.regime import RegimeRow

        stmt = (
            select(RegimeRow)
            .where(RegimeRow.symbol == symbol)
            .order_by(desc(RegimeRow.since))
            .limit(1)
        )
        res = await session.execute(stmt)
        row = res.scalars().first()
    except Exception:
        return Regime.SIDEWAYS
    if row is None:
        return Regime.SIDEWAYS
    try:
        return Regime(row.regime)
    except ValueError:
        return Regime.SIDEWAYS


async def _persist_signal(session, signal: Signal) -> None:
    from pfip.models.signals import SignalRow

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


# ---------------------------------------------------------------------------
# Core run
# ---------------------------------------------------------------------------


def _confidence_from_proba(proba: float) -> int:
    """0..1 calibrated prob -> 0..100 confidence (distance from 0.5)."""
    return max(0, min(100, int(round(abs(proba - 0.5) * 200.0))))


def _direction(proba: float, model: LGBMBaselineModel) -> SignalDirection:
    if proba >= model.buy_threshold:
        return SignalDirection.BUY
    if proba <= model.sell_threshold:
        return SignalDirection.SELL
    return SignalDirection.HOLD


def _champion_for(regime: Any) -> tuple[Any, str | None]:
    """Load the pinned champion model for ``regime`` from the registry.

    Returns ``(model, version)`` or ``(None, None)`` so the caller falls back to
    inline walk-forward training. The champion is produced by the weekly
    ``signals.retrain`` pass (OOS-gated), trained on the same ``FEATURE_COLUMNS``
    fed here — so it predicts the latest bar directly, no training needed.
    """
    try:
        from pfip.signals.registry import get_pinned, load_pickle

        reg = regime.value if hasattr(regime, "value") else str(regime)
        entry = get_pinned(task="signal", regime=reg, horizon="3d")
        if entry is None:
            return None, None
        model = load_pickle(entry, current_schema_revision=None)
        return model, entry.version
    except Exception as exc:  # noqa: BLE001 — registry optional; fall back to inline
        log.warning("champion load failed for %s: %s", regime, exc)
        return None, None


async def run_for_symbol(
    session,
    symbol: str,
    *,
    source: str = "coinbase",
    timeframe: str = "1d",
    persist: bool = True,
) -> SignalRunResult:
    """Predict + persist a signal for one symbol.

    Uses the registry **champion** for the symbol's regime when one is pinned
    (retrained weekly, OOS-gated); otherwise falls back to inline walk-forward
    training on the trailing window.
    """
    df = await _load_recent_ohlcv(session, symbol, source, timeframe)
    if df.empty or len(df) < 80:
        return SignalRunResult(
            symbol=symbol,
            direction=SignalDirection.HOLD,
            confidence=0,
            regime=Regime.SIDEWAYS,
            status="no-data",
        )

    feats = compute_features(df)
    feats = feats[[c for c in FEATURE_COLUMNS if c in feats.columns]].copy()
    feats = feats.dropna()
    if feats.empty:
        return SignalRunResult(
            symbol=symbol,
            direction=SignalDirection.HOLD,
            confidence=0,
            regime=Regime.SIDEWAYS,
            status="features-empty",
        )

    regime = await _current_regime(session, symbol)

    # Prefer the registry champion (weekly-retrained, OOS-gated) — it predicts
    # the latest bar directly. Fall back to inline walk-forward training when no
    # champion is pinned for this regime yet.
    champion, model_version_override = _champion_for(regime)
    model = champion
    if champion is not None:
        try:
            calibrated_last = float(model.predict_proba_up(feats.iloc[[-1]])[0])
        except Exception as exc:  # noqa: BLE001 — degrade to inline on any failure
            log.warning("champion predict failed for %s: %s", symbol, exc)
            champion = None

    if champion is None:
        model_version_override = None
        router = RegimeRouter()
        model = router.get(regime)

        y = make_label(df["close"], horizon=model.horizon).reindex(feats.index)
        valid = y.dropna().index
        if len(valid) < 60:
            return SignalRunResult(
                symbol=symbol,
                direction=SignalDirection.HOLD,
                confidence=0,
                regime=regime,
                status="not-enough-labels",
            )

        # Walk-forward train; the model ends up fit to the most recent training
        # window so .predict_proba on the latest row is in-sample free.
        try:
            wf_df = model.walk_forward_train(
                features=feats.loc[valid],
                close=df["close"].loc[valid],
                train_window=min(756, max(60, len(valid) - 30)),
                step=21,
                test_window=21,
                embargo=5,
            )
        except Exception as exc:
            log.warning("walk_forward_train failed for %s: %s", symbol, exc)
            wf_df = pd.DataFrame()

        if wf_df.empty:
            # Fall back to one-shot train on everything-up-to-now-21 for embargo.
            cutoff = len(valid) - 21
            if cutoff < 30:
                return SignalRunResult(
                    symbol=symbol,
                    direction=SignalDirection.HOLD,
                    confidence=0,
                    regime=regime,
                    status="not-enough-labels",
                )
            train_idx = valid[:cutoff]
            model.fit(feats.loc[train_idx], y.loc[train_idx])
            raw_last = float(model.predict_proba_up(feats.iloc[[-1]])[0])
            calibrated_last = raw_last
        else:
            # Calibrate predictions using the WF holdout data.
            raw = wf_df["proba_up"].to_numpy()
            yt = wf_df["y"].to_numpy()
            _, calibrator = _calibrate_probabilities(raw, yt, method="isotonic")
            raw_last = float(model.predict_proba_up(feats.iloc[[-1]])[0])
            if calibrator is not None:
                try:  # pragma: no cover
                    calibrated_last = float(
                        calibrator.transform([float(np.clip(raw_last, 0.0, 1.0))])[0]
                    )
                except Exception:
                    calibrated_last = raw_last
            else:
                calibrated_last = raw_last

    # Direction + confidence after calibration.
    direction = _direction(calibrated_last, model)
    confidence = _confidence_from_proba(calibrated_last)
    if confidence < model.confidence_floor:
        direction = SignalDirection.HOLD

    # SHAP drivers (best-effort).
    pred_out = model.predict_row(feats.iloc[-1])

    signal = Signal(
        direction=direction,
        confidence=confidence,
        horizon_hours=24 * model.horizon,
        drivers=pred_out.drivers,
        counter_arguments=pred_out.counter_arguments,
        regime=regime,
        model_name=model.model_name,
        model_version=model_version_override or model.model_version,
        asset=symbol,
        generated_at=datetime.now(tz=timezone.utc),
    )

    if persist:
        try:
            await _persist_signal(session, signal)
        except Exception as exc:  # pragma: no cover
            log.warning("persist_signal failed for %s: %s", symbol, exc)

    return SignalRunResult(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        regime=regime,
        signal=signal,
        status="ok",
    )


async def run_for_watchlist(
    session,
    timeframe: str = "1d",
) -> list[SignalRunResult]:
    """Generate signals for every watchlist symbol."""
    try:
        from pfip.models.watchlist import WatchlistRow

        res = await session.execute(select(WatchlistRow))
        rows = list(res.scalars().all())
    except Exception as exc:  # pragma: no cover
        log.warning("watchlist load failed: %s", exc)
        return []

    from pfip.db.sources import resolve_ohlcv_source

    out: list[SignalRunResult] = []
    for r in rows:
        symbol = str(r.symbol)
        # Use the source that ACTUALLY ingested this symbol (US equities live
        # under 'tiingo', not the heuristic's 'yfinance' — otherwise the
        # scheduled signal flow reads 0 rows and silently zeroes US signals).
        source = await resolve_ohlcv_source(session, symbol, timeframe) or _source_for(symbol)
        try:
            result = await run_for_symbol(
                session, symbol=symbol, source=source, timeframe=timeframe
            )
        except Exception as exc:  # pragma: no cover
            log.warning("signal run failed for %s: %s", symbol, exc)
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
