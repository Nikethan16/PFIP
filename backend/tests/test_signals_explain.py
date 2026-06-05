"""Tests for the per-prediction explanation layer.

We use a tiny sklearn LogisticRegression as the test model — it has
predict_proba, so the explainer goes through the standard path. The
contribution sign and ranking should track the model's coefficients.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from pfip.signals.explain import (
    Driver,
    drivers_to_dicts,
    explain_prediction,
    top_k_drivers,
)


@pytest.fixture
def trained_model() -> tuple[LogisticRegression, list[str], np.ndarray]:
    """Train a logistic regression where feature 0 has a strong positive
    effect, feature 1 a strong negative effect, feature 2 nearly zero."""
    rng = np.random.default_rng(42)
    n = 500
    x0 = rng.normal(0, 1, n)
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    # y = 1 when 2*x0 - 2*x1 > 0
    logits = 2 * x0 - 2 * x1
    y = (logits > 0).astype(int)
    X = np.column_stack([x0, x1, x2])
    model = LogisticRegression(random_state=42).fit(X, y)
    return model, ["x0", "x1", "x2"], X


def test_explain_returns_one_driver_per_feature(trained_model):
    model, names, X = trained_model
    drivers = explain_prediction(
        model, X[0], feature_names=names, background=X, method="permutation"
    )
    assert len(drivers) == 3
    assert {d.feature for d in drivers} == {"x0", "x1", "x2"}
    assert all(isinstance(d, Driver) for d in drivers)


def test_explain_picks_correct_sign_for_known_direction(trained_model):
    """For a row with high x0 (positive coef), the contribution of x0
    must be positive. For a row with low x0, it must be negative."""
    model, names, X = trained_model
    x_high = np.array([3.0, 0.0, 0.0])
    x_low = np.array([-3.0, 0.0, 0.0])
    d_high = explain_prediction(
        model, x_high, feature_names=names, background=X, method="permutation"
    )
    d_low = explain_prediction(
        model, x_low, feature_names=names, background=X, method="permutation"
    )
    x0_high = next(d for d in d_high if d.feature == "x0")
    x0_low = next(d for d in d_low if d.feature == "x0")
    assert x0_high.contribution > 0
    assert x0_low.contribution < 0


def test_explain_noise_feature_ranks_low(trained_model):
    """x2 has near-zero coefficient — must be smaller |contribution| than x0/x1."""
    model, names, X = trained_model
    drivers = explain_prediction(
        model, X[0], feature_names=names, background=X, method="permutation"
    )
    by_feat = {d.feature: abs(d.contribution) for d in drivers}
    assert by_feat["x2"] < by_feat["x0"]
    assert by_feat["x2"] < by_feat["x1"]


def test_top_k_drivers_orders_by_abs_contribution(trained_model):
    model, names, X = trained_model
    drivers = explain_prediction(
        model, X[0], feature_names=names, background=X, method="permutation"
    )
    top = top_k_drivers(drivers, k=2)
    assert len(top) == 2
    # First entry must have ≥ |contribution| than second.
    assert abs(top[0].contribution) >= abs(top[1].contribution)


def test_drivers_to_dicts_roundtrip(trained_model):
    """Serialization preserves all three fields per row."""
    model, names, X = trained_model
    drivers = explain_prediction(
        model, X[0], feature_names=names, background=X, method="permutation"
    )
    payload = drivers_to_dicts(drivers)
    assert len(payload) == 3
    for d in payload:
        assert set(d.keys()) == {"feature", "value", "contribution"}
        assert isinstance(d["feature"], str)
        assert isinstance(d["value"], float)
        assert isinstance(d["contribution"], float)


def test_explain_length_mismatch_raises():
    """Mismatched feature_names vs x_row → ValueError."""
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (50, 3))
    y = (X[:, 0] > 0).astype(int)
    model = LogisticRegression().fit(X, y)
    with pytest.raises(ValueError):
        explain_prediction(
            model,
            X[0],
            feature_names=["only_one_name"],
            background=X,
            method="permutation",
        )


def test_explain_handles_model_with_only_predict():
    """Model with no predict_proba or decision_function should still work."""

    class PredictOnly:
        """Returns predictions in {0, 1}; the permutation path falls back
        to using `predict` because predict_proba is absent."""

        def predict(self, X):  # noqa: N803
            return (np.asarray(X)[:, 0] > 0).astype(int)

    model = PredictOnly()
    rng = np.random.default_rng(1)
    X = rng.normal(0, 1, (50, 2))
    drivers = explain_prediction(
        model,
        np.array([1.5, 0.0]),
        feature_names=["a", "b"],
        background=X,
        method="permutation",
    )
    assert len(drivers) == 2
