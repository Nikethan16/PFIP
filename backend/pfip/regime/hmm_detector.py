"""Hidden-Markov-Model regime detector.

Wraps ``hmmlearn.hmm.GaussianHMM`` with a fixed number of states (default 4).
The raw HMM emits anonymous state indices; we map them to one of the four
plan-specified ``Regime`` labels (``bull_trend`` / ``bear_trend`` / ``sideways``
/ ``high_volatility``) based on the fitted per-state mean return and volatility.

Usage:
    detector = HMMRegimeDetector(n_states=4)
    detector.fit(returns_series)               # returns_series = pd.Series of log returns
    preds = detector.predict(returns_series)   # -> list[Regime]
    frame = detector.score_per_bar(price_df)   # -> DataFrame[regime, confidence]

Persisting to MLflow:
    detector.persist_to_mlflow(run_name=...)

Fallbacks: if ``hmmlearn`` is unavailable at runtime, we fall back to a simple
rule-based regime classifier that inspects rolling mean + std of returns. This
keeps the module importable in test environments without the C extension.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pfip.core.contracts import Regime

log = logging.getLogger(__name__)


# Try hmmlearn — fall back gracefully if missing.
try:  # pragma: no cover — exercised only with/without dep
    from hmmlearn.hmm import GaussianHMM  # type: ignore[import-untyped]

    _HMMLEARN_OK = True
except Exception as exc:  # pragma: no cover
    log.warning("hmmlearn unavailable (%s); falling back to rule-based regime", exc)
    GaussianHMM = None  # type: ignore[assignment,misc]
    _HMMLEARN_OK = False


@dataclass(frozen=True)
class RegimePrediction:
    """A single-bar regime prediction."""

    regime: Regime
    confidence: float
    state: int


class HMMRegimeDetector:
    """Gaussian HMM regime detector with a plan-regime mapping layer.

    Args:
        n_states: number of hidden states (3 or 4). Default 4.
        covariance_type: GaussianHMM covariance type (default ``diag``).
        n_iter: EM iterations (default 200).
        random_state: RNG seed for reproducibility.
    """

    def __init__(
        self,
        n_states: int = 4,
        covariance_type: str = "diag",
        n_iter: int = 200,
        random_state: int = 42,
    ) -> None:
        if n_states not in (3, 4):
            raise ValueError("n_states must be 3 or 4 (plan spec)")
        self.n_states = n_states
        self.covariance_type = covariance_type
        self.n_iter = n_iter
        self.random_state = random_state

        self._model: Any = None
        self._state_to_regime: dict[int, Regime] = {}
        self._state_stats: dict[int, dict[str, float]] = {}
        self._fitted: bool = False

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, returns_series: pd.Series) -> HMMRegimeDetector:
        """Fit the HMM on a series of log returns."""
        if returns_series is None or len(returns_series) < 50:
            raise ValueError("fit() needs at least 50 observations of log returns")

        x = np.asarray(returns_series, dtype=float)
        x = x[~np.isnan(x)]
        if len(x) < 50:
            raise ValueError("fit() needs >=50 non-NaN observations after cleaning")

        x_col = x.reshape(-1, 1)

        if _HMMLEARN_OK:
            model = GaussianHMM(
                n_components=self.n_states,
                covariance_type=self.covariance_type,
                n_iter=self.n_iter,
                random_state=self.random_state,
            )
            model.fit(x_col)
            self._model = model
            # per-state stats
            means = model.means_.flatten()
            # For diag covariance hmmlearn stores ``covars_`` of shape (n, n_features)
            covars = np.asarray(model.covars_).reshape(self.n_states, -1)
            stds = np.sqrt(np.clip(covars[:, 0], 1e-12, None))
        else:
            # Fallback: k-means-ish split on returns. We rank the bars by return
            # and split into n_states quantiles; within each we compute mean/std.
            q = np.linspace(0, 1, self.n_states + 1)
            edges = np.quantile(x, q)
            edges[0] -= 1e-9
            edges[-1] += 1e-9
            means = np.zeros(self.n_states)
            stds = np.zeros(self.n_states)
            for s in range(self.n_states):
                mask = (x > edges[s]) & (x <= edges[s + 1])
                if mask.any():
                    means[s] = float(np.mean(x[mask]))
                    stds[s] = float(np.std(x[mask]) + 1e-12)
                else:
                    means[s] = 0.0
                    stds[s] = 1e-6
            self._model = {"fallback_edges": edges, "means": means, "stds": stds}

        self._state_stats = {
            int(s): {"mean": float(means[s]), "std": float(stds[s])} for s in range(self.n_states)
        }
        self._state_to_regime = self._map_states_to_regimes(means, stds)
        self._fitted = True
        return self

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, returns_series: pd.Series) -> list[Regime]:
        """Predict the regime label for every observation in ``returns_series``."""
        self._require_fitted()
        x = np.asarray(returns_series, dtype=float)
        mask = ~np.isnan(x)
        states = self._predict_states(x[mask])
        full = np.full(len(x), -1, dtype=int)
        full[mask] = states
        out: list[Regime] = []
        for s in full.tolist():
            if s < 0:
                out.append(Regime.SIDEWAYS)
            else:
                out.append(self._state_to_regime[int(s)])
        return out

    def score_per_bar(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame with columns ``regime`` and ``confidence`` per bar.

        ``df`` must contain a ``close`` column; we compute log returns internally.
        Confidence is the HMM posterior probability of the assigned state (or
        1.0 for the fallback classifier).
        """
        self._require_fitted()
        if "close" not in df.columns:
            raise ValueError("score_per_bar needs a 'close' column")
        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        log_ret = np.log(close / close.shift(1))
        x = log_ret.to_numpy()
        mask = ~np.isnan(x)

        states = np.full(len(x), -1, dtype=int)
        confs = np.zeros(len(x), dtype=float)

        if not mask.any():
            return pd.DataFrame(
                {"regime": [Regime.SIDEWAYS.value] * len(x), "confidence": [0.0] * len(x)},
                index=df.index,
            )

        x_clean = x[mask].reshape(-1, 1)
        if _HMMLEARN_OK and not isinstance(self._model, dict):
            post = self._model.predict_proba(x_clean)  # shape (n, n_states)
            sub_states = post.argmax(axis=1)
            sub_confs = post.max(axis=1)
        else:
            sub_states = self._predict_states_fallback(x[mask])
            sub_confs = np.ones(len(sub_states))

        states[mask] = sub_states
        confs[mask] = sub_confs

        regimes: list[str] = []
        for s in states.tolist():
            if s < 0:
                regimes.append(Regime.SIDEWAYS.value)
            else:
                regimes.append(self._state_to_regime[int(s)].value)

        return pd.DataFrame({"regime": regimes, "confidence": confs}, index=df.index)

    # ------------------------------------------------------------------
    # MLflow persistence
    # ------------------------------------------------------------------

    def persist_to_mlflow(
        self,
        run_name: str,
        artifact_dir: str | Path = "/tmp/mlflow/artifacts",
    ) -> str | None:
        """Log the fitted model + its state-regime mapping to MLflow.

        Returns the MLflow run ID, or ``None`` if MLflow is unavailable. Falls
        back to a local joblib dump if MLflow import fails so the flow still
        persists something.
        """
        self._require_fitted()

        try:  # pragma: no cover — hit only when mlflow is installed
            import joblib
            import mlflow

            with mlflow.start_run(run_name=run_name) as run:
                mlflow.log_param("n_states", self.n_states)
                mlflow.log_param("covariance_type", self.covariance_type)
                mlflow.log_param("random_state", self.random_state)
                for s, stats in self._state_stats.items():
                    mlflow.log_metric(f"state{s}_mean", stats["mean"])
                    mlflow.log_metric(f"state{s}_std", stats["std"])

                out_dir = Path(artifact_dir) / run.info.run_id
                out_dir.mkdir(parents=True, exist_ok=True)
                model_path = out_dir / "hmm_detector.joblib"
                joblib.dump(
                    {
                        "model": self._model,
                        "state_to_regime": {k: v.value for k, v in self._state_to_regime.items()},
                        "state_stats": self._state_stats,
                        "hmmlearn_ok": _HMMLEARN_OK,
                    },
                    model_path,
                )
                mlflow.log_artifact(str(model_path))
                return run.info.run_id
        except Exception as exc:
            log.warning("MLflow persistence failed (%s); writing local joblib only", exc)
            try:
                import joblib

                out_dir = Path(artifact_dir) / f"local_{run_name}"
                out_dir.mkdir(parents=True, exist_ok=True)
                joblib.dump(
                    {
                        "model": self._model,
                        "state_to_regime": {k: v.value for k, v in self._state_to_regime.items()},
                        "state_stats": self._state_stats,
                    },
                    out_dir / "hmm_detector.joblib",
                )
            except Exception as exc2:
                log.warning("Local joblib dump also failed: %s", exc2)
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("HMMRegimeDetector must be fit() before use")

    def _predict_states(self, x: np.ndarray) -> np.ndarray:
        if _HMMLEARN_OK and not isinstance(self._model, dict):
            return self._model.predict(x.reshape(-1, 1)).astype(int)
        return self._predict_states_fallback(x)

    def _predict_states_fallback(self, x: np.ndarray) -> np.ndarray:
        assert isinstance(self._model, dict)
        edges = self._model["fallback_edges"]
        states = np.zeros(len(x), dtype=int)
        for i, v in enumerate(x):
            for s in range(self.n_states):
                if edges[s] < v <= edges[s + 1]:
                    states[i] = s
                    break
            else:
                states[i] = self.n_states - 1
        return states

    def _map_states_to_regimes(self, means: np.ndarray, stds: np.ndarray) -> dict[int, Regime]:
        """Deterministic mapping by mean return and vol.

        Algorithm:
        1. Identify the highest-volatility state → ``HIGH_VOLATILITY``.
        2. Of the remaining, the max-mean state → ``BULL_TREND``,
           the min-mean state → ``BEAR_TREND``, and anything else → ``SIDEWAYS``.
        For 3 states we skip the ``SIDEWAYS`` bucket and map the middle state
        straight to ``SIDEWAYS``.
        """
        n = len(means)
        # Sort states by std descending; highest vol is HIGH_VOLATILITY.
        order_by_std = np.argsort(-stds)
        mapping: dict[int, Regime] = {}
        hv_state = int(order_by_std[0])
        mapping[hv_state] = Regime.HIGH_VOLATILITY

        remaining = [s for s in range(n) if s != hv_state]
        rem_means = {s: means[s] for s in remaining}
        # Sort by mean
        sorted_rem = sorted(rem_means.items(), key=lambda kv: kv[1])
        # lowest mean = bear, highest = bull
        if sorted_rem:
            mapping[int(sorted_rem[0][0])] = Regime.BEAR_TREND
        if len(sorted_rem) >= 2:
            mapping[int(sorted_rem[-1][0])] = Regime.BULL_TREND
        # any leftover middle states
        for s, _m in sorted_rem[1:-1]:
            mapping[int(s)] = Regime.SIDEWAYS

        return mapping
