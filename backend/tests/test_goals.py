"""Tests for goal-based planning + Monte Carlo projection (pfip.portfolio.goals).

Pure-logic tests (no DB) plus an API smoke test for POST /portfolio/goals/project.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pfip.portfolio.goals import (
    GoalProjection,
    project_goal,
    required_monthly_contribution,
    simulate_terminal_values,
)


# ---------------------------------------------------------------------------
# simulate_terminal_values
# ---------------------------------------------------------------------------


def test_zero_volatility_is_deterministic():
    """No vol ⇒ every path identical and matches closed-form compounding."""
    vals = simulate_terminal_values(
        current_corpus_inr=100_000,
        monthly_contribution_inr=0,
        years=1,
        expected_annual_return=0.10,
        annual_volatility=0.0,
        n_sims=500,
    )
    assert np.allclose(vals, vals[0])
    # One year of 10% on a lump sum with no contributions ≈ 110,000.
    assert vals[0] == pytest.approx(110_000, rel=1e-6)


def test_contributions_increase_terminal_value():
    base = simulate_terminal_values(
        current_corpus_inr=0,
        monthly_contribution_inr=0,
        years=5,
        expected_annual_return=0.08,
        annual_volatility=0.0,
        n_sims=200,
    )
    with_sip = simulate_terminal_values(
        current_corpus_inr=0,
        monthly_contribution_inr=10_000,
        years=5,
        expected_annual_return=0.08,
        annual_volatility=0.0,
        n_sims=200,
    )
    assert with_sip[0] > base[0]


def test_seed_makes_it_reproducible():
    kw = dict(
        current_corpus_inr=50_000,
        monthly_contribution_inr=5_000,
        years=3,
        expected_annual_return=0.10,
        annual_volatility=0.15,
        n_sims=300,
        seed=7,
    )
    a = simulate_terminal_values(**kw)
    b = simulate_terminal_values(**kw)
    assert np.array_equal(a, b)


def test_no_negative_net_worth():
    vals = simulate_terminal_values(
        current_corpus_inr=10_000,
        monthly_contribution_inr=0,
        years=10,
        expected_annual_return=-0.5,
        annual_volatility=0.9,
        n_sims=500,
    )
    assert (vals >= 0).all()


@pytest.mark.parametrize("years", [0, -1])
def test_invalid_years_raises(years):
    with pytest.raises(ValueError):
        simulate_terminal_values(
            current_corpus_inr=1,
            monthly_contribution_inr=0,
            years=years,
            expected_annual_return=0.1,
            annual_volatility=0.1,
        )


# ---------------------------------------------------------------------------
# project_goal
# ---------------------------------------------------------------------------


def test_project_goal_percentiles_are_ordered():
    p = project_goal(
        current_corpus_inr=100_000,
        monthly_contribution_inr=10_000,
        years=10,
        expected_annual_return=0.10,
        annual_volatility=0.15,
        n_sims=2000,
    )
    assert isinstance(p, GoalProjection)
    assert p.p10 <= p.p25 <= p.p50 <= p.p75 <= p.p90


def test_project_goal_reports_total_contributed():
    p = project_goal(
        current_corpus_inr=0,
        monthly_contribution_inr=10_000,
        years=10,
        expected_annual_return=0.0,
        annual_volatility=0.0,
        n_sims=100,
    )
    assert p.total_contributed_inr == pytest.approx(10_000 * 120)


def test_probability_of_target_between_zero_and_one():
    p = project_goal(
        current_corpus_inr=100_000,
        monthly_contribution_inr=10_000,
        years=10,
        expected_annual_return=0.10,
        annual_volatility=0.20,
        target_inr=2_500_000,
        n_sims=2000,
    )
    assert p.probability_of_target is not None
    assert 0.0 <= p.probability_of_target <= 1.0


def test_higher_target_is_less_likely():
    kw = dict(
        current_corpus_inr=100_000,
        monthly_contribution_inr=10_000,
        years=10,
        expected_annual_return=0.10,
        annual_volatility=0.20,
        n_sims=3000,
    )
    low = project_goal(target_inr=1_500_000, **kw).probability_of_target
    high = project_goal(target_inr=5_000_000, **kw).probability_of_target
    assert high <= low


# ---------------------------------------------------------------------------
# required_monthly_contribution
# ---------------------------------------------------------------------------


def test_required_contribution_zero_when_already_there():
    # A huge corpus already clears a tiny target at the median with no SIP.
    req = required_monthly_contribution(
        current_corpus_inr=10_000_000,
        target_inr=1_000_000,
        years=5,
        expected_annual_return=0.08,
        annual_volatility=0.10,
        n_sims=500,
    )
    assert req == 0.0


def test_required_contribution_hits_target_at_median():
    target = 5_000_000
    req = required_monthly_contribution(
        current_corpus_inr=100_000,
        target_inr=target,
        years=10,
        expected_annual_return=0.10,
        annual_volatility=0.15,
        n_sims=2000,
    )
    assert req > 0
    # Feeding the solved contribution back should land the median near target.
    p = project_goal(
        current_corpus_inr=100_000,
        monthly_contribution_inr=req,
        years=10,
        expected_annual_return=0.10,
        annual_volatility=0.15,
        target_inr=target,
        n_sims=2000,
    )
    assert p.p50 == pytest.approx(target, rel=0.05)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_goals_project_requires_auth(client: TestClient):
    resp = client.post(
        "/api/v1/portfolio/goals/project",
        json={
            "current_corpus_inr": 100000,
            "years": 10,
        },
    )
    assert resp.status_code == 401


def test_goals_project_endpoint(client: TestClient, auth_headers: dict[str, str]):
    resp = client.post(
        "/api/v1/portfolio/goals/project",
        headers=auth_headers,
        json={
            "current_corpus_inr": 100000,
            "monthly_contribution_inr": 10000,
            "years": 10,
            "expected_annual_return": 0.10,
            "annual_volatility": 0.15,
            "target_inr": 2500000,
            "n_sims": 2000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "percentiles_inr" in body
    assert "probability_of_target" in body
    assert "required_monthly_contribution_inr" in body
    assert "disclaimer" in body


def test_goals_project_rejects_bad_years(client: TestClient, auth_headers: dict[str, str]):
    resp = client.post(
        "/api/v1/portfolio/goals/project",
        headers=auth_headers,
        json={"current_corpus_inr": 100000, "years": 0},
    )
    assert resp.status_code == 422
