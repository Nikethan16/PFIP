"""Tests for SIP tracking — XIRR + corpus projection (pfip.portfolio.sip)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from pfip.portfolio.sip import CashFlow, project_sip_corpus, sip_summary, xirr


# ---------------------------------------------------------------------------
# xirr
# ---------------------------------------------------------------------------


def test_xirr_known_one_year_double():
    # Invest 1000 today, worth 1100 in exactly one year ⇒ XIRR ≈ 10%.
    flows = [CashFlow(date(2025, 1, 1), -1000.0), CashFlow(date(2026, 1, 1), 1100.0)]
    r = xirr(flows)
    assert r == pytest.approx(0.10, abs=1e-3)


def test_xirr_flat_is_zero():
    flows = [CashFlow(date(2025, 1, 1), -1000.0), CashFlow(date(2026, 1, 1), 1000.0)]
    assert xirr(flows) == pytest.approx(0.0, abs=1e-4)


def test_xirr_monthly_sip_positive_return():
    # 12 monthly investments of 1000, ending value above total invested ⇒ XIRR > 0.
    flows = [CashFlow(date(2025, m, 1), -1000.0) for m in range(1, 13)]
    flows.append(CashFlow(date(2025, 12, 31), 13000.0))  # 12k in, 13k out
    r = xirr(flows)
    assert r is not None and r > 0


def test_xirr_no_sign_change_returns_none():
    flows = [CashFlow(date(2025, 1, 1), -1000.0), CashFlow(date(2026, 1, 1), -500.0)]
    assert xirr(flows) is None


def test_xirr_single_flow_returns_none():
    assert xirr([CashFlow(date(2025, 1, 1), -1000.0)]) is None


def test_xirr_negative_return_detected():
    flows = [CashFlow(date(2025, 1, 1), -1000.0), CashFlow(date(2026, 1, 1), 800.0)]
    r = xirr(flows)
    assert r is not None and r < 0


# ---------------------------------------------------------------------------
# project_sip_corpus
# ---------------------------------------------------------------------------


def test_zero_return_corpus_is_sum_of_instalments():
    out = project_sip_corpus(monthly_amount=1000, years=1, annual_return=0.0)
    assert out["projected_corpus_inr"] == pytest.approx(12000, abs=1e-6)
    assert out["gain_inr"] == pytest.approx(0.0, abs=1e-6)


def test_positive_return_grows_corpus():
    out = project_sip_corpus(monthly_amount=1000, years=10, annual_return=0.12)
    assert out["projected_corpus_inr"] > out["total_invested_inr"]
    assert out["gain_inr"] > 0


def test_existing_corpus_compounds():
    with_seed = project_sip_corpus(
        monthly_amount=0, years=10, annual_return=0.10, current_corpus=100000
    )
    # 100k at 10% for 10y ≈ 259k.
    assert with_seed["projected_corpus_inr"] == pytest.approx(259374, rel=0.01)


def test_negative_years_raises():
    with pytest.raises(ValueError):
        project_sip_corpus(monthly_amount=1000, years=-1, annual_return=0.1)


# ---------------------------------------------------------------------------
# sip_summary
# ---------------------------------------------------------------------------


def test_sip_summary_reports_invested_and_xirr():
    instal = [CashFlow(date(2025, m, 1), -1000.0) for m in range(1, 13)]
    out = sip_summary(instal, current_value=13000.0)
    assert out["total_invested_inr"] == 12000.0
    assert out["n_instalments"] == 12
    assert out["xirr"] is not None
    assert out["absolute_gain_inr"] == 1000.0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_sip_xirr_endpoint(client: TestClient, auth_headers: dict[str, str]):
    resp = client.post(
        "/api/v1/portfolio/sip/xirr",
        headers=auth_headers,
        json={
            "instalments": [
                {"date": "2025-01-01", "amount": -1000},
                {"date": "2025-02-01", "amount": -1000},
            ],
            "current_value_inr": 2100,
        },
    )
    assert resp.status_code == 200
    assert "xirr" in resp.json()


def test_sip_project_endpoint(client: TestClient, auth_headers: dict[str, str]):
    resp = client.post(
        "/api/v1/portfolio/sip/project",
        headers=auth_headers,
        json={"monthly_amount_inr": 10000, "years": 10, "annual_return": 0.12},
    )
    assert resp.status_code == 200
    assert "projected_corpus_inr" in resp.json()


def test_sip_requires_auth(client: TestClient):
    assert client.post("/api/v1/portfolio/sip/project", json={
        "monthly_amount_inr": 1000, "years": 5,
    }).status_code == 401
