"""Prefect flow: train one LightGBM signal model per regime.

For each (symbol, regime, horizon) tuple, this flow:

1. Pulls historical features + the regime label for every row.
2. Splits into the rows where regime == target regime.
3. Builds labels via :func:`pfip.signals.lgbm_baseline.make_label`.
4. Calls :meth:`LGBMBaselineModel.fit`.
5. Persists the model to MLflow *and* to the file-backed model registry
   (``pfip.signals.registry``).
6. Marks the new model as the pinned champion for the slot if no pin
   exists, else leaves it for human review.

Data fetching is delegated to :func:`_load_training_data`; for now we
assume features live in a wide table keyed by (symbol, ts). The flow is
tolerant of an empty training set per slot — it logs and continues.

Schedule: weekly on Sundays 03:00 UTC, before the Sunday weekly review
runs (13:30 UTC). Both bands are quiet enough to absorb a few-minute
training pass.
"""

from __future__ import annotations

import pickle
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from prefect import flow, get_run_logger, task

from pfip.signals.lgbm_baseline import LGBMBaselineModel, make_label
from pfip.signals.registry import get_pinned, pin_model, upload_model


_REGIMES = ("bull_trend", "sideways", "high_volatility", "bear_trend", "accumulation")
_HORIZONS = (1, 5, 21)


@task(name="lgbm-load-training-data")
async def _load_training_data(symbol: str, *, since: datetime | None = None) -> pd.DataFrame:
    """Return a wide DataFrame indexed by ts with feature columns and a
    `regime` column.

    Real implementation reads from `features` + `regime` tables; we keep
    it as a thin shim so the training flow tests at unit level (with a
    fake DataFrame) and integration level (with the real DB)."""
    # Local import to keep cold-start cheap when the flow is just registered.
    from sqlalchemy import select

    from pfip.db.session import get_sessionmaker
    from pfip.models.features import FeaturesRow
    from pfip.models.regime import RegimeRow
    from pfip.models.ohlcv import OHLCVRow

    factory = get_sessionmaker()
    async with factory() as session:
        feat_q = await session.execute(select(FeaturesRow).where(FeaturesRow.symbol == symbol))
        features = feat_q.scalars().all()
        if not features:
            return pd.DataFrame()

        regime_q = await session.execute(select(RegimeRow).where(RegimeRow.symbol == symbol))
        regimes = sorted(regime_q.scalars().all(), key=lambda r: r.since)

        ohlcv_q = await session.execute(select(OHLCVRow).where(OHLCVRow.symbol == symbol))
        ohlcv = ohlcv_q.scalars().all()

    # Build a per-ts DataFrame.
    feat_df = pd.DataFrame(
        [{**f.payload, "ts": f.ts} for f in features if isinstance(f.payload, dict)]
    )
    if feat_df.empty:
        return pd.DataFrame()
    feat_df["ts"] = pd.to_datetime(feat_df["ts"], utc=True)
    feat_df = feat_df.set_index("ts").sort_index()

    close = pd.Series(
        [float(r.close) for r in sorted(ohlcv, key=lambda r: r.ts)],
        index=pd.to_datetime([r.ts for r in sorted(ohlcv, key=lambda r: r.ts)], utc=True),
        name="close",
    )
    feat_df = feat_df.join(close, how="left")

    # Forward-fill regime label per row.
    regime_series = pd.Series(
        [r.regime for r in regimes],
        index=pd.to_datetime([r.since for r in regimes], utc=True),
        name="regime",
    )
    regime_aligned = regime_series.reindex(feat_df.index, method="ffill")
    feat_df["regime"] = regime_aligned
    if since is not None:
        feat_df = feat_df[feat_df.index >= since.replace(tzinfo=timezone.utc)]
    return feat_df


def slice_per_regime(df: pd.DataFrame, regime: str) -> pd.DataFrame:
    """Return only the rows where regime == target. Pure function (no DB)."""
    if df.empty or "regime" not in df.columns:
        return df.iloc[0:0]
    return df[df["regime"] == regime]


def train_one(
    df: pd.DataFrame, *, horizon: int, random_state: int = 42
) -> tuple[LGBMBaselineModel, dict[str, float]] | None:
    """Train a single LGBMBaselineModel on `df`. Returns (model, metrics) or None.

    Tolerates absent LightGBM by short-circuiting to None (caller logs).
    """
    if df.empty or "close" not in df.columns or len(df) < 100:
        return None
    y = make_label(df["close"], horizon=horizon)
    feature_cols = [c for c in df.columns if c not in ("close", "regime")]
    X = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    # Align lengths after the label shift.
    aligned = pd.concat([X, y.rename("label")], axis=1).dropna()
    if len(aligned) < 100:
        return None
    X = aligned.drop(columns=["label"])
    y = aligned["label"]
    try:
        model = LGBMBaselineModel(random_state=random_state)
        model.fit(X, y)
    except Exception:  # pragma: no cover — lightgbm missing or unrecoverable
        return None
    # Cheap in-sample metrics (for the registry; real OOS lives in backtest).
    try:
        proba = model.predict_proba_up(X)
        accuracy = float(((proba > 0.5).astype(int) == y).mean())
    except Exception:
        accuracy = float("nan")
    return model, {"insample_accuracy": accuracy, "n_rows": float(len(X))}


@task(name="lgbm-train-one-slot")
def _train_slot(
    df: pd.DataFrame, *, symbol: str, regime: str, horizon: int
) -> dict[str, Any] | None:
    sliced = slice_per_regime(df, regime)
    result = train_one(sliced, horizon=horizon)
    if result is None:
        return None
    model, metrics = result

    # Pickle to a temp file and upload to the registry.
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fp:
        pickle.dump(model, fp)
        path = Path(fp.name)
    try:
        entry = upload_model(
            path,
            name=f"lgbm_{symbol.replace('/', '_')}_{regime}_{horizon}d",
            kind="pkl",
            task="signal",
            regime=regime,
            horizon=f"{horizon}d",
            version=datetime.now(tz=timezone.utc).strftime("v%Y%m%dT%H%MZ"),
            metrics=metrics,
            notes=f"Trained by train_lgbm_per_regime on {symbol}",
        )
    finally:
        path.unlink(missing_ok=True)

    # Pin only if no existing champion — never silently demote.
    existing = get_pinned(task="signal", regime=regime, horizon=f"{horizon}d")
    if existing is None:
        pin_model(entry.id, task="signal", regime=regime, horizon=f"{horizon}d")
    return {
        "regime": regime,
        "horizon": horizon,
        "rows": int(metrics.get("n_rows", 0)),
        "in_sample_acc": metrics.get("insample_accuracy", 0.0),
        "model_id": entry.id,
        "pinned": existing is None,
    }


@flow(name="train-lgbm-per-regime", log_prints=True)
async def train_lgbm_per_regime(
    symbol: str = "BTC/USD", horizons: tuple[int, ...] = _HORIZONS
) -> list[dict[str, Any]]:
    """Train one model per (regime, horizon) slot for ``symbol``."""
    logger = get_run_logger()
    df = await _load_training_data(symbol)
    if df.empty:
        logger.warning("No training data for {} — skipping", symbol)
        return []

    results: list[dict[str, Any]] = []
    for regime in _REGIMES:
        for h in horizons:
            out = _train_slot(df, symbol=symbol, regime=regime, horizon=h)
            if out is None:
                logger.info(
                    "Skipped: {} regime={} horizon={}d (insufficient data)", symbol, regime, h
                )
                continue
            results.append(out)
            logger.info(
                "Trained: {} regime={} horizon={}d → {} rows, in-sample acc {:.3f}",
                symbol,
                regime,
                h,
                out["rows"],
                out["in_sample_acc"],
            )
    return results


if __name__ == "__main__":
    import asyncio

    asyncio.run(train_lgbm_per_regime())
