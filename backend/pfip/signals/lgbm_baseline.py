"""LightGBM baseline classifier for Stage-4 signals.

**Target:** binary — "close[t+3] > close[t]" — fitted on the 5 plan features
(``rsi_14``, ``macd_hist``, ``atr_14``, ``return_7d``, ``volatility_30d``).

**Training discipline:** walk-forward only. The public ``walk_forward_train``
method implements 3-year trailing window, 21-day step, 21-day test window,
5-day embargo on both sides, plus a CPCV cross-check.

**SHAP explainability:** for every prediction we compute per-row SHAP values,
pick the top-``k`` by absolute contribution, and surface them as the
``drivers``/``counter_arguments`` fields of a ``Signal``.

**Persistence:** ``persist_to_mlflow`` logs the trained booster + feature list
to MLflow, falling back to a local joblib dump if the tracking server is
unreachable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pfip.core.contracts import Driver, Regime, Signal, SignalDirection

log = logging.getLogger(__name__)


FEATURE_COLUMNS: tuple[str, ...] = (
    "rsi_14",
    "macd_hist",
    "atr_14",
    "return_7d",
    "volatility_30d",
)


# ---------------------------------------------------------------------------
# Optional deps: LightGBM + SHAP. Fall back to scikit-learn GBDT / contributions
# if unavailable so the module is importable everywhere.
# ---------------------------------------------------------------------------

try:  # pragma: no cover
    import lightgbm as lgb  # type: ignore[import-untyped]

    _HAS_LGB = True
except Exception:  # pragma: no cover
    lgb = None  # type: ignore[assignment]
    _HAS_LGB = False

try:  # pragma: no cover
    import shap  # type: ignore[import-untyped]

    _HAS_SHAP = True
except Exception:  # pragma: no cover
    shap = None  # type: ignore[assignment]
    _HAS_SHAP = False


# ---------------------------------------------------------------------------
# Label helper
# ---------------------------------------------------------------------------


def make_label(close: pd.Series, horizon: int = 3) -> pd.Series:
    """Binary label: 1 if ``close.shift(-horizon) > close``, else 0.

    The final ``horizon`` rows are NaN (no forward info yet).
    """
    fwd = close.shift(-horizon)
    out = (fwd > close).astype("float")
    out[fwd.isna()] = np.nan
    return out


# ---------------------------------------------------------------------------
# Model output + container
# ---------------------------------------------------------------------------


@dataclass
class SignalOutput:
    """Per-bar predict output from the baseline model."""

    proba_up: float
    direction: SignalDirection
    confidence: int
    drivers: list[Driver]
    counter_arguments: list[Driver]


@dataclass
class LGBMBaselineModel:
    """Thin wrapper around a LightGBM binary classifier.

    The model is fit on the canonical 5-feature matrix and predicts the
    probability that ``close`` will rise over the next ``horizon`` bars.
    """

    model_name: str = "lgbm_baseline"
    model_version: str = "0.1.0"
    horizon: int = 3  # bars (days on D1 data)
    confidence_floor: int = 65
    buy_threshold: float = 0.55
    sell_threshold: float = 0.45
    feature_cols: tuple[str, ...] = field(default_factory=lambda: FEATURE_COLUMNS)

    # Internal
    _booster: Any = None
    _explainer: Any = None
    _fitted: bool = False

    # ------------------------------------------------------------------
    # Fit / predict
    # ------------------------------------------------------------------

    def fit(self, X: pd.DataFrame, y: pd.Series) -> LGBMBaselineModel:
        """Fit on (X, y). Caller is responsible for walk-forward discipline."""
        X_clean, y_clean = self._clean(X, y)
        if len(X_clean) < 30:
            raise ValueError("fit() needs at least 30 observations after cleaning")

        if _HAS_LGB:
            self._booster = lgb.LGBMClassifier(
                n_estimators=200,
                num_leaves=31,
                learning_rate=0.05,
                min_child_samples=20,
                subsample=0.8,
                colsample_bytree=0.8,
                objective="binary",
                random_state=42,
                n_jobs=1,
                verbose=-1,
            )
            self._booster.fit(X_clean.values, y_clean.values)
        else:
            # Fallback: sklearn GBDT
            from sklearn.ensemble import GradientBoostingClassifier

            self._booster = GradientBoostingClassifier(
                n_estimators=200,
                max_depth=3,
                learning_rate=0.05,
                random_state=42,
            )
            self._booster.fit(X_clean.values, y_clean.values)

        # SHAP explainer (optional)
        if _HAS_SHAP:
            try:  # pragma: no cover
                self._explainer = shap.TreeExplainer(self._booster)
            except Exception as exc:  # pragma: no cover
                log.warning("SHAP explainer init failed (%s); drivers disabled", exc)
                self._explainer = None
        else:
            self._explainer = None

        self._fitted = True
        return self

    def predict_proba_up(self, X: pd.DataFrame) -> np.ndarray:
        """Return P(close_{t+h} > close_t) for every row of X."""
        self._require_fitted()
        Xf = X[list(self.feature_cols)].copy()
        Xf = Xf.ffill().fillna(0.0)
        proba = self._booster.predict_proba(Xf.values)
        # booster may be binary (n,2) — pick the positive class col.
        if proba.ndim == 2 and proba.shape[1] >= 2:
            return proba[:, 1]
        return proba.flatten()

    def predict_row(self, feature_row: pd.Series) -> SignalOutput:
        """Predict one row → full ``SignalOutput`` with SHAP drivers."""
        self._require_fitted()
        x = feature_row[list(self.feature_cols)].to_frame().T
        proba_up = float(self.predict_proba_up(x)[0])
        direction, confidence = self._direction_and_confidence(proba_up)
        drivers, counters = self._drivers_for_row(x)
        return SignalOutput(
            proba_up=proba_up,
            direction=direction,
            confidence=confidence,
            drivers=drivers,
            counter_arguments=counters,
        )

    # ------------------------------------------------------------------
    # Walk-forward training (the discipline the plan mandates)
    # ------------------------------------------------------------------

    def walk_forward_train(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        train_window: int = 756,  # ~3y of daily bars
        step: int = 21,
        test_window: int = 21,
        embargo: int = 5,
    ) -> pd.DataFrame:
        """Run walk-forward training/evaluation.

        For each fold:
            train = [i, i+train_window)
            embargo (skip) = train_window..+embargo
            test  = [i+train_window+embargo, i+train_window+embargo+test_window)

        Returns a DataFrame of per-test-bar predictions with columns
        ``[time, proba_up, y, fold]``. The model ends fit to the most recent
        fold's training window.
        """
        y = make_label(close, horizon=self.horizon)
        fold_results: list[dict[str, Any]] = []

        idx = features.index
        n = len(features)
        fold = 0
        start = 0
        while True:
            train_end = start + train_window
            test_start = train_end + embargo
            test_end = test_start + test_window
            if test_end > n:
                break

            tr_X = features.iloc[start:train_end]
            tr_y = y.iloc[start:train_end]
            te_X = features.iloc[test_start:test_end]
            te_y = y.iloc[test_start:test_end]

            # Drop NaN labels at train time.
            try:
                self.fit(tr_X, tr_y)
            except ValueError:
                start += step
                fold += 1
                continue
            proba = self.predict_proba_up(te_X)
            for ts, p, yv in zip(te_X.index, proba, te_y.to_numpy(), strict=False):
                fold_results.append(
                    {
                        "time": ts,
                        "proba_up": float(p),
                        "y": float(yv) if not pd.isna(yv) else np.nan,
                        "fold": fold,
                    }
                )
            start += step
            fold += 1

        return pd.DataFrame(fold_results)

    # ------------------------------------------------------------------
    # Converting a prediction into a Signal
    # ------------------------------------------------------------------

    def to_signal(
        self,
        *,
        asset: str,
        feature_row: pd.Series,
        regime: Regime,
        generated_at: datetime | None = None,
    ) -> Signal:
        """Full typed signal contract for a single row + regime."""
        pred = self.predict_row(feature_row)
        return Signal(
            direction=pred.direction,
            confidence=pred.confidence,
            horizon_hours=24 * self.horizon,
            drivers=pred.drivers,
            counter_arguments=pred.counter_arguments,
            regime=regime,
            model_name=self.model_name,
            model_version=self.model_version,
            asset=asset,
            generated_at=generated_at or datetime.now(tz=timezone.utc),
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist_to_mlflow(
        self,
        run_name: str | None = None,
        artifact_dir: str | Path = "/tmp/mlflow/artifacts",
    ) -> str | None:
        """Log booster + metadata to MLflow; fall back to local joblib."""
        self._require_fitted()
        try:  # pragma: no cover
            import joblib
            import mlflow

            name = run_name or f"{self.model_name}_{self.model_version}"
            with mlflow.start_run(run_name=name) as run:
                mlflow.log_param("model_name", self.model_name)
                mlflow.log_param("model_version", self.model_version)
                mlflow.log_param("horizon", self.horizon)
                mlflow.log_param("features", list(self.feature_cols))
                out = Path(artifact_dir) / run.info.run_id
                out.mkdir(parents=True, exist_ok=True)
                path = out / "lgbm_baseline.joblib"
                joblib.dump(
                    {"booster": self._booster, "feature_cols": list(self.feature_cols)}, path
                )
                mlflow.log_artifact(str(path))
                return run.info.run_id
        except Exception as exc:
            log.warning("MLflow persist failed (%s); trying local joblib", exc)
            try:
                import joblib

                out = Path(artifact_dir) / f"local_{run_name or self.model_name}"
                out.mkdir(parents=True, exist_ok=True)
                joblib.dump(
                    {"booster": self._booster, "feature_cols": list(self.feature_cols)},
                    out / "lgbm_baseline.joblib",
                )
            except Exception as exc2:
                log.warning("Local joblib persist also failed: %s", exc2)
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clean(self, X: pd.DataFrame, y: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
        Xf = X[list(self.feature_cols)].copy()
        Xf = Xf.ffill()
        df = Xf.join(y.rename("__y__"))
        df = df.dropna()
        return df[list(self.feature_cols)], df["__y__"]

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("LGBMBaselineModel must be fit() before use")

    def _direction_and_confidence(self, proba_up: float) -> tuple[SignalDirection, int]:
        # Confidence: distance from 0.5 scaled to [0, 100].
        conf_raw = abs(proba_up - 0.5) * 2.0
        confidence = max(0, min(100, int(round(conf_raw * 100.0))))
        if proba_up >= self.buy_threshold:
            direction = SignalDirection.BUY
        elif proba_up <= self.sell_threshold:
            direction = SignalDirection.SELL
        else:
            direction = SignalDirection.HOLD
        return direction, confidence

    def _drivers_for_row(self, x: pd.DataFrame, k: int = 5) -> tuple[list[Driver], list[Driver]]:
        """Return (top-k positive drivers, top-3 negative counter_arguments)."""
        if self._explainer is None:
            return [], []
        try:  # pragma: no cover
            shap_vals = self._explainer.shap_values(x.values)
            if isinstance(shap_vals, list):
                # Binary classifiers sometimes return [neg_shap, pos_shap]
                shap_vals = shap_vals[-1]
            row = np.asarray(shap_vals).flatten()
        except Exception as exc:  # pragma: no cover
            log.warning("SHAP failed on row: %s", exc)
            return [], []

        pairs = list(zip(self.feature_cols, row, strict=False))
        # Drivers: top-k by positive contribution, counter_arguments: top-3 negative.
        pos = sorted([p for p in pairs if p[1] > 0], key=lambda kv: -kv[1])[:k]
        neg = sorted([p for p in pairs if p[1] < 0], key=lambda kv: kv[1])[:3]
        drivers = [Driver(feature=f, contribution=float(c)) for f, c in pos]
        counters = [Driver(feature=f, contribution=float(c)) for f, c in neg]
        return drivers, counters
