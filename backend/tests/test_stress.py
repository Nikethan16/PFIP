"""Tests for portfolio stress-testing (pfip.portfolio.stress)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pfip.portfolio.stress import SCENARIOS, stress_book


def test_all_scenarios_present():
    out = stress_book({"equity": 100000.0})
    keys = {s["scenario"] for s in out["scenarios"]}
    assert keys == set(SCENARIOS)


def test_gfc_hits_equity_hard():
    out = stress_book({"equity": 100000.0})
    gfc = next(s for s in out["scenarios"] if s["scenario"] == "gfc_2008")
    # -55% equity shock ⇒ ~-55k.
    assert gfc["change_inr"] < -50000
    assert gfc["impact_pct"] < -0.5


def test_total_value_reported():
    out = stress_book({"equity": 100000.0, "bond": 50000.0})
    assert out["current_value_inr"] == 150000.0


def test_results_sorted_worst_first():
    out = stress_book({"equity": 100000.0, "crypto_exchange": 100000.0})
    impacts = [s["impact_pct"] for s in out["scenarios"]]
    assert impacts == sorted(impacts)


def test_inr_depreciation_helps_crypto():
    # A book that is all crypto should GAIN under INR depreciation.
    out = stress_book({"crypto_exchange": 100000.0})
    inr = next(s for s in out["scenarios"] if s["scenario"] == "inr_depreciation_10pct")
    assert inr["change_inr"] > 0


def test_empty_book_no_crash():
    out = stress_book({})
    assert out["current_value_inr"] == 0.0
    for s in out["scenarios"]:
        assert s["impact_pct"] == 0.0


def test_stress_endpoint(client: TestClient, auth_headers: dict[str, str]):
    resp = client.get("/api/v1/portfolio/stress-test", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "scenarios" in body and "current_value_inr" in body


def test_stress_requires_auth(client: TestClient):
    assert client.get("/api/v1/portfolio/stress-test").status_code == 401
