"""Calibration engine per plan 8.4.

Exports pure functions that compute the calibration metrics the plan calls
for and one helper that implements the "ECE > 0.15 for 2 months" suspension
rule.

    compute_brier_score(y_true, y_prob)            -> float
    compute_ece(y_true, y_prob, n_bins)            -> float
    reliability_diagram(y_true, y_prob, n_bins)    -> list[ReliabilityBin]
    sharpness(y_prob)                              -> float
    check_suspension_rule(ece_history, threshold, n) -> bool
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class ReliabilityBin:
    """One reliability-bin data-point for a reliability diagram."""

    lower: float
    upper: float
    predicted_mean: float
    observed_freq: float
    count: int


@dataclass(frozen=True)
class CalibrationSummary:
    """Bundle of calibration metrics for one (model, market, period)."""

    brier: float
    ece: float
    sharpness: float
    reliability: list[ReliabilityBin]
    n_samples: int


def _as_arrays(
    y_true: Sequence[float] | np.ndarray, y_prob: Sequence[float] | np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    y_t = np.asarray(y_true, dtype=float).ravel()
    y_p = np.asarray(y_prob, dtype=float).ravel()
    if y_t.shape != y_p.shape:
        raise ValueError(
            f"y_true and y_prob must have the same shape; got {y_t.shape} vs {y_p.shape}"
        )
    # Clip probs defensively.
    y_p = np.clip(y_p, 0.0, 1.0)
    return y_t, y_p


def compute_brier_score(
    y_true: Sequence[float] | np.ndarray, y_prob: Sequence[float] | np.ndarray
) -> float:
    """Mean squared error between predicted probability and realised outcome."""
    y_t, y_p = _as_arrays(y_true, y_prob)
    if len(y_t) == 0:
        return float("nan")
    return float(np.mean((y_p - y_t) ** 2))


def reliability_diagram(
    y_true: Sequence[float] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    n_bins: int = 10,
) -> list[ReliabilityBin]:
    """Bucket predictions into ``n_bins`` equal-width bins and return observed vs predicted."""
    y_t, y_p = _as_arrays(y_true, y_prob)
    if len(y_t) == 0:
        return []

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[ReliabilityBin] = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        if i == 0:
            mask = (y_p >= lo) & (y_p <= hi)
        else:
            mask = (y_p > lo) & (y_p <= hi)
        count = int(mask.sum())
        if count == 0:
            predicted_mean = float((lo + hi) / 2.0)
            observed_freq = 0.0
        else:
            predicted_mean = float(y_p[mask].mean())
            observed_freq = float(y_t[mask].mean())
        out.append(
            ReliabilityBin(
                lower=float(lo),
                upper=float(hi),
                predicted_mean=predicted_mean,
                observed_freq=observed_freq,
                count=count,
            )
        )
    return out


def compute_ece(
    y_true: Sequence[float] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error: weighted |predicted - observed| over bins."""
    y_t, y_p = _as_arrays(y_true, y_prob)
    if len(y_t) == 0:
        return float("nan")
    bins = reliability_diagram(y_t, y_p, n_bins=n_bins)
    total = len(y_t)
    if total == 0:
        return float("nan")
    ece = 0.0
    for b in bins:
        if b.count == 0:
            continue
        ece += (b.count / total) * abs(b.predicted_mean - b.observed_freq)
    return float(ece)


def sharpness(y_prob: Sequence[float] | np.ndarray) -> float:
    """Standard deviation of the predicted probability — the plan's sharpness."""
    y_p = np.asarray(y_prob, dtype=float).ravel()
    if len(y_p) < 2:
        return 0.0
    return float(np.std(np.clip(y_p, 0.0, 1.0), ddof=1))


def check_suspension_rule(
    ece_history: Sequence[float],
    threshold: float = 0.15,
    n_consecutive: int = 2,
) -> bool:
    """Return True if the last ``n_consecutive`` ECEs all exceed ``threshold``.

    Plan 8.4: "If a model's ECE exceeds 0.15 for two consecutive months →
    model is suspended." Caller is responsible for ordering ``ece_history``
    chronologically.
    """
    if len(ece_history) < n_consecutive:
        return False
    tail = list(ece_history)[-n_consecutive:]
    return all(v > threshold for v in tail)
