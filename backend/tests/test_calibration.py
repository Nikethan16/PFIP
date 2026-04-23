"""Calibration router smoke tests + calibration math unit tests."""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from pfip.calibration.brier_ece import (
    check_suspension_rule,
    compute_brier_score,
    compute_ece,
    reliability_diagram,
    sharpness,
)


def test_calibration_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/calibration/latest")
    assert resp.status_code == 401


def test_calibration_returns_empty_list_when_no_data(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/calibration/latest", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_brier_perfect_zero() -> None:
    assert compute_brier_score([1, 0, 1, 0], [1.0, 0.0, 1.0, 0.0]) == 0.0


def test_brier_coin_flip_half() -> None:
    b = compute_brier_score([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5])
    assert math.isclose(b, 0.25, rel_tol=1e-9)


def test_ece_perfect_is_zero() -> None:
    # All predictions are 1.0 when y is 1; ECE should be near zero
    y_true = [1] * 50 + [0] * 50
    y_prob = [1.0] * 50 + [0.0] * 50
    assert compute_ece(y_true, y_prob, n_bins=10) < 0.05


def test_reliability_diagram_shape() -> None:
    y_true = [1, 0] * 50
    y_prob = [i / 100 for i in range(100)]
    bins = reliability_diagram(y_true, y_prob, n_bins=10)
    assert len(bins) == 10
    assert sum(b.count for b in bins) == 100


def test_sharpness_constant_is_zero() -> None:
    assert sharpness([0.5] * 10) == 0.0


def test_sharpness_nonzero_for_spread() -> None:
    assert sharpness([0.1, 0.9, 0.1, 0.9]) > 0.0


def test_suspension_rule_triggers() -> None:
    assert check_suspension_rule([0.1, 0.2, 0.17], threshold=0.15, n_consecutive=2) is True


def test_suspension_rule_does_not_trigger_on_single_breach() -> None:
    assert check_suspension_rule([0.1, 0.2, 0.1], threshold=0.15, n_consecutive=2) is False
