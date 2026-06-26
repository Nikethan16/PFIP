"""Plain-async per-regime LightGBM retraining with a champion/challenger gate.

Replaces the broken Prefect ``train_lgbm_per_regime`` flow (Prefect 2.20 is
incompatible with the upgraded ``anyio``). Design:

* **Same features as serving.** Trains on ``compute_features`` →
  ``FEATURE_COLUMNS`` (exactly what ``signals.runner`` feeds the model at predict
  time), so a registered champion is feature-compatible with live signals.
* **Pooled per regime.** Pools rows across the whole watchlist for each regime
  (far more data than a single symbol), trains one model per regime.
* **Honest OOS gate.** Holds out the most-recent ``_TEST_DAYS`` as a time-split
  test set; a freshly-trained model is **only promoted to champion if its OOS
  hit-rate beats the incumbent** (or there is no incumbent). Non-promoted models
  are still archived as challengers.

Runs weekly via ``scripts.run_weekly`` (the ``pfip-weekly.timer`` on the VM),
writing to the durable file registry at ``data/model_registry``. Live signals
load the pinned champion (see ``signals.runner``) and fall back to inline
walk-forward training when no champion exists.
"""

from __future__ import annotations

import logging
import pickle
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from pfip.signals.lgbm_baseline import FEATURE_COLUMNS, LGBMBaselineModel, make_label
from pfip.signals.registry import get_pinned, pin_model, upload_model

log = logging.getLogger("pfip.signals.retrain")

TASK = "signal"
HORIZON = 3
HORIZON_STR = "3d"
REGIMES = (
    "bull_trend",
    "bear_trend",
    "sideways",
    "high_volatility",
    "accumulation",
    "distribution",
)
_MIN_ROWS = 150
_TEST_DAYS = 90  # most-recent window held out for the OOS gate


async def _symbol_frame(session, symbol: str) -> pd.DataFrame:
    """Per-symbol frame indexed by ts: FEATURE_COLUMNS + __regime + __label."""
    from pfip.db.sources import resolve_ohlcv_source
    from pfip.features.technicals import compute_features
    from pfip.models.ohlcv import OHLCVRow

    source = await resolve_ohlcv_source(session, symbol, "1d")
    if not source:
        return pd.DataFrame()
    since = datetime.now(tz=UTC) - timedelta(days=365 * 3)
    rows = (
        (
            await session.execute(
                select(OHLCVRow)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.source == source,
                    OHLCVRow.timeframe == "1d",
                    OHLCVRow.time >= since,
                )
                .order_by(OHLCVRow.time.asc())
            )
        )
        .scalars()
        .all()
    )
    if len(rows) < _MIN_ROWS:
        return pd.DataFrame()
    df = pd.DataFrame(
        [
            {
                "time": r.time,
                "close": float(r.close),
                "high": float(r.high),
                "low": float(r.low),
                "open": float(r.open),
                "volume": float(r.volume),
            }
            for r in rows
        ]
    ).set_index("time")
    feats = compute_features(df)
    cols = [c for c in FEATURE_COLUMNS if c in feats.columns]
    feats = feats[cols].dropna()
    if feats.empty:
        return pd.DataFrame()
    label = make_label(df["close"], horizon=HORIZON).reindex(feats.index)

    # Label every bar's regime with the HMM detector. RegimeRow only stores the
    # recent daily labels (one per pipeline run), not a 3-year history, so we
    # re-derive per-bar regimes here — the same detector the regime stage uses.
    regime_vals = np.array([None] * len(feats), dtype=object)
    try:
        from pfip.regime.hmm_detector import HMMRegimeDetector

        returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        if len(returns) >= 80 and float(returns.std()) > 1e-9:
            detector = HMMRegimeDetector(n_states=4)
            detector.fit(returns)
            per_bar = detector.score_per_bar(df)
            regime_vals = per_bar["regime"].reindex(feats.index, method="ffill").to_numpy()
    except Exception as exc:  # — HMM optional; leave bars unlabelled
        log.warning("retrain: regime labeling failed for %s: %s", symbol, exc)

    out = feats.copy()
    out["__regime"] = regime_vals
    out["__label"] = label.to_numpy()
    return out.dropna(subset=[*cols, "__label"])


async def retrain_universe(session) -> dict[str, Any]:
    """Retrain + (gated) promote one champion per regime across the watchlist."""
    from pfip.models.watchlist import WatchlistRow

    symbols = [str(r.symbol) for r in (await session.execute(select(WatchlistRow))).scalars().all()]
    frames: list[pd.DataFrame] = []
    for sym in symbols:
        try:
            f = await _symbol_frame(session, sym)
            if not f.empty:
                frames.append(f)
        except Exception as exc:  # — one symbol can't abort the pass
            log.warning("retrain: frame failed for %s: %s", sym, exc)
    if not frames:
        return {"trained": 0, "error": "no training data"}

    pooled = pd.concat(frames)
    feat_cols = [c for c in FEATURE_COLUMNS if c in pooled.columns]
    cutoff = datetime.now(tz=UTC) - timedelta(days=_TEST_DAYS)

    results: list[dict[str, Any]] = []
    for regime in REGIMES:
        sl = pooled[pooled["__regime"] == regime]
        if len(sl) < _MIN_ROWS:
            continue
        X = sl[feat_cols].apply(pd.to_numeric, errors="coerce")
        y = (sl["__label"].astype(float) > 0.5).astype(int)
        keep = X.dropna().index
        X, y = X.loc[keep], y.loc[keep]
        if len(X) < _MIN_ROWS:
            continue

        # Time-split OOS gate score.
        idx = pd.to_datetime(X.index, utc=True)
        is_test = np.asarray(idx >= cutoff)
        oos_hit = float("nan")
        try:
            if is_test.sum() >= 20 and (~is_test).sum() >= 60:
                mval = LGBMBaselineModel()
                mval.fit(X[~is_test], y[~is_test])
                proba = mval.predict_proba_up(X[is_test])
                oos_hit = float(((proba > 0.5).astype(int) == y[is_test].to_numpy()).mean())
        except Exception as exc:
            log.warning("retrain: OOS score failed for %s: %s", regime, exc)

        # Final model on all of this regime's data.
        try:
            model = LGBMBaselineModel()
            model.fit(X, y)
        except Exception as exc:
            log.warning("retrain: fit failed for %s: %s", regime, exc)
            continue

        # Champion/challenger gate.
        champ = get_pinned(task=TASK, regime=regime, horizon=HORIZON_STR)
        champ_score = champ.metrics.get("oos_hit_rate") if champ else None
        promote = champ is None or (
            not np.isnan(oos_hit) and (champ_score is None or oos_hit > champ_score)
        )

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fp:
            pickle.dump(model, fp)
            path = Path(fp.name)
        try:
            entry = upload_model(
                path,
                name=f"lgbm_pooled_{regime}_{HORIZON_STR}",
                kind="pkl",
                task=TASK,
                regime=regime,
                horizon=HORIZON_STR,
                version=datetime.now(tz=UTC).strftime("v%Y%m%dT%H%MZ"),
                metrics={
                    "oos_hit_rate": 0.0 if np.isnan(oos_hit) else round(oos_hit, 4),
                    "n_rows": float(len(X)),
                },
                notes="pooled per-regime retrain (de-Prefected)",
            )
        finally:
            path.unlink(missing_ok=True)

        if promote:
            pin_model(entry.id, task=TASK, regime=regime, horizon=HORIZON_STR)

        results.append(
            {
                "regime": regime,
                "n_rows": int(len(X)),
                "oos_hit_rate": None if np.isnan(oos_hit) else round(oos_hit, 4),
                "champion_score": champ_score,
                "promoted": bool(promote),
                "model_id": entry.id,
            }
        )
        log.info(
            "retrain %s: n=%d oos=%s promoted=%s",
            regime,
            len(X),
            "n/a" if np.isnan(oos_hit) else f"{oos_hit:.3f}",
            promote,
        )

    return {"trained": len(results), "regimes": results}


__all__ = ["retrain_universe", "TASK", "HORIZON_STR", "REGIMES"]
