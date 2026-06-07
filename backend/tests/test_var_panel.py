"""Smoke tests for GET /portfolio/var (dashboard VaR panel)."""

from __future__ import annotations

from fastapi.testclient import TestClient

# The exact field set the frontend VarPanelSchema (frontend/lib/api.ts) requires.
_REQUIRED_FIELDS = {
    "var_95_inr",
    "var_99_inr",
    "var_95_pct",
    "var_99_pct",
    "window_days",
    "concentration_hhi",
    "drawdown_series",
    "daily_new_positions_remaining",
    "sharpe_30d",
    "day_change_inr",
    "day_change_pct",
}


def test_var_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/portfolio/var")
    assert resp.status_code == 401


def test_var_returns_graceful_zero_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    """With no holdings (fake session) every field is present + correctly typed."""
    resp = client.get("/api/v1/portfolio/var", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert _REQUIRED_FIELDS.issubset(body.keys())

    # All numeric fields are plain JSON numbers (NOT strings) per VarPanelSchema.
    for key in (
        "var_95_inr",
        "var_99_inr",
        "var_95_pct",
        "var_99_pct",
        "concentration_hhi",
        "sharpe_30d",
        "day_change_inr",
        "day_change_pct",
    ):
        assert isinstance(body[key], (int, float)), f"{key} must be numeric"

    assert isinstance(body["window_days"], int)
    assert isinstance(body["daily_new_positions_remaining"], int)
    assert isinstance(body["drawdown_series"], list)

    # Empty portfolio ⇒ a correct zero shape (no fabricated VaR).
    assert body["var_95_inr"] == 0.0
    assert body["var_99_inr"] == 0.0
    assert body["concentration_hhi"] == 0.0
    # Default daily cap is 2, none added today ⇒ 2 remaining.
    assert body["daily_new_positions_remaining"] == 2


def test_var_respects_positions_added_today(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/portfolio/var?positions_added_today=2", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["daily_new_positions_remaining"] == 0
