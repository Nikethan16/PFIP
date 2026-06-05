"""Per-prediction SHAP-style explanations for signals.

For tree models we use real SHAP (lazy-imported) when available; for any
model — and when SHAP isn't installed — we fall back to a permutation-
importance approximation that's cheap, deterministic, and correct in
direction (which feature *pushed* the prediction up vs down).

Output is a list of ``Driver`` dicts persisted to ``signals.drivers``
(JSONB column) and rendered as the "Top 5 drivers" panel on the Signals
page. The list is signed: positive contribution means the feature
*increased* the model's probability of the predicted class; negative
means it pulled the other way.

Public surface:

- :class:`Driver` — small typed dict.
- :func:`explain_prediction` — main entry. Accepts (model, X_row, X_background).
- :func:`top_k_drivers` — pick top-K by absolute contribution.
- :func:`drivers_to_dicts` — JSON-serializable serialization for the DB.

We intentionally avoid the full SHAP library by default; the fallback
is sufficient for the "show me why" UI need, and adding `shap` to
`requirements.txt` adds 100+ MB of transitive numpy/llvmlite deps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np


@dataclass(slots=True)
class Driver:
    """One feature contribution to a single prediction."""

    feature: str
    value: float  # the actual feature value used at prediction time
    contribution: float  # signed; |contribution| is what's ranked


def _is_finite(x: Any) -> bool:
    try:
        return np.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _predict_proba_safely(model: Any, x: np.ndarray) -> np.ndarray:
    """Return a 1d array of P(class=1) for a 2d X.

    Tolerates:
        - models with predict_proba returning shape (n, 2) → take column 1
        - models with predict_proba returning shape (n, k) for k>2 → take argmax row
        - models without predict_proba but with `decision_function`
        - models with only `predict` → 0/1 outputs cast to float
    """
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(x))
        if proba.ndim == 2 and proba.shape[1] == 2:
            return proba[:, 1]
        if proba.ndim == 2:
            return proba.max(axis=1)
        return proba.ravel()
    if hasattr(model, "decision_function"):
        return np.asarray(model.decision_function(x)).ravel()
    if hasattr(model, "predict"):
        return np.asarray(model.predict(x), dtype=float).ravel()
    raise ValueError(
        "model has none of predict_proba / decision_function / predict — "
        "cannot explain a prediction."
    )


def _shap_explain(
    model: Any, x_row: np.ndarray, background: np.ndarray
) -> np.ndarray | None:
    """Try real SHAP. Returns None if unavailable; never raises."""
    try:
        import shap  # type: ignore  # pragma: no cover — optional dep
    except ImportError:
        return None
    try:  # pragma: no cover — optional path
        explainer = shap.TreeExplainer(model)
        vals = explainer.shap_values(x_row.reshape(1, -1))
        # shap returns either a 2d (n, k) array for multiclass or 1d (k).
        if isinstance(vals, list):
            vals = vals[-1]  # take positive-class for binary
        return np.asarray(vals).ravel()
    except Exception:
        return None


def _permutation_explain(
    model: Any,
    x_row: np.ndarray,
    background: np.ndarray,
) -> np.ndarray:
    """Cheap, deterministic explanation.

    For each feature ``i`` we replace ``x_row[i]`` with the *median* of
    that feature in the background dataset, compute the predicted
    probability before and after, and return the *signed* difference:

        contribution_i = P(class=1 | x_row) - P(class=1 | x_row with i replaced)

    Positive ⇒ the original feature value pushed the prediction up.

    Cost: ``n_features`` extra forward passes, all in one batched call.
    """
    if background.shape[1] != x_row.shape[0]:
        raise ValueError(
            f"background has {background.shape[1]} features but x_row has {x_row.shape[0]}"
        )
    n_features = x_row.shape[0]
    medians = np.median(background, axis=0)
    base_p = _predict_proba_safely(model, x_row.reshape(1, -1))[0]

    # Build the counterfactual matrix: one row per feature, that feature
    # replaced with the background median.
    counterfactuals = np.tile(x_row, (n_features, 1)).astype(float)
    for i in range(n_features):
        counterfactuals[i, i] = medians[i]

    cf_p = _predict_proba_safely(model, counterfactuals)
    # contribution = base - counterfactual; positive means the feature pulled up.
    return base_p - cf_p


def explain_prediction(
    model: Any,
    x_row: Sequence[float] | np.ndarray,
    *,
    feature_names: Sequence[str],
    background: np.ndarray | None = None,
    method: str = "auto",
) -> list[Driver]:
    """Compute per-feature contributions for one prediction.

    Args:
        model: any sklearn-compatible estimator. Must expose at least one
            of ``predict_proba`` / ``decision_function`` / ``predict``.
        x_row: 1d feature vector for the prediction being explained.
        feature_names: names aligned to ``x_row``.
        background: 2d background dataset for permutation. If None we
            substitute zeros (less informative but always available).
        method: ``"auto"`` (try SHAP, fall back to permutation),
            ``"shap"`` (force SHAP — returns empty if unavailable),
            ``"permutation"`` (force permutation).

    Returns:
        list of Driver entries in the order of ``feature_names``.
    """
    x = np.asarray(x_row, dtype=float).ravel()
    if len(x) != len(feature_names):
        raise ValueError(
            f"feature_names ({len(feature_names)}) and x_row ({len(x)}) length mismatch"
        )
    if background is None:
        background = np.zeros((1, len(x)))

    contributions: np.ndarray | None = None
    if method in ("auto", "shap"):
        contributions = _shap_explain(model, x, background)
        if contributions is None and method == "shap":
            # Caller forced shap and we couldn't deliver — return empty.
            return []

    if contributions is None:
        contributions = _permutation_explain(model, x, background)

    drivers: list[Driver] = []
    for i, (name, val) in enumerate(zip(feature_names, x)):
        c = float(contributions[i]) if _is_finite(contributions[i]) else 0.0
        drivers.append(
            Driver(feature=str(name), value=float(val) if _is_finite(val) else 0.0, contribution=c)
        )
    return drivers


def top_k_drivers(drivers: list[Driver], *, k: int = 5) -> list[Driver]:
    """Pick top-K by absolute contribution."""
    return sorted(drivers, key=lambda d: abs(d.contribution), reverse=True)[:k]


def drivers_to_dicts(drivers: list[Driver]) -> list[dict[str, Any]]:
    """Serialize for the JSONB column."""
    return [
        {"feature": d.feature, "value": d.value, "contribution": d.contribution}
        for d in drivers
    ]


__all__ = [
    "Driver",
    "drivers_to_dicts",
    "explain_prediction",
    "top_k_drivers",
]
