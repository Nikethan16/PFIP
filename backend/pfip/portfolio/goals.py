"""Goal-based planning + Monte Carlo net-worth projection.

Answers the question every personal-finance app should: *"Given what I have
now and what I keep adding each month, will I hit my goal — and with what
confidence?"*

The engine is **pure** (numpy only, no DB, seedable) so it is trivially
testable and reusable from the API, the agent, and the morning brief. Returns
are simulated monthly via geometric Brownian-motion-style steps:

    value_{t+1} = value_t * (1 + r_t) + monthly_contribution
    r_t ~ Normal(monthly_mean, monthly_vol)

where ``monthly_mean = (1 + annual_return)**(1/12) - 1`` and
``monthly_vol = annual_volatility / sqrt(12)``.

Everything is advisory — no figure here is a promise; it is a distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# A goal further out than this is almost certainly a typo; cap the sim cost.
_MAX_YEARS = 80
_DEFAULT_SIMS = 10_000


@dataclass(frozen=True)
class GoalProjection:
    """Distribution of terminal net worth for a savings plan."""

    years: float
    n_months: int
    current_corpus_inr: float
    monthly_contribution_inr: float
    expected_annual_return: float
    annual_volatility: float
    total_contributed_inr: float
    # Terminal-value percentiles (INR).
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    mean: float
    # Probability the terminal value reaches the target (None when no target).
    target_inr: float | None = None
    probability_of_target: float | None = None

    def as_dict(self) -> dict:
        out = {
            "years": self.years,
            "n_months": self.n_months,
            "current_corpus_inr": self.current_corpus_inr,
            "monthly_contribution_inr": self.monthly_contribution_inr,
            "expected_annual_return": self.expected_annual_return,
            "annual_volatility": self.annual_volatility,
            "total_contributed_inr": self.total_contributed_inr,
            "percentiles_inr": {
                "p10": self.p10,
                "p25": self.p25,
                "p50": self.p50,
                "p75": self.p75,
                "p90": self.p90,
            },
            "expected_inr": self.mean,
        }
        if self.target_inr is not None:
            out["target_inr"] = self.target_inr
            out["probability_of_target"] = self.probability_of_target
        return out


def _monthly_params(annual_return: float, annual_volatility: float) -> tuple[float, float]:
    """Convert annual return/vol to per-month mean/std."""
    monthly_mean = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
    monthly_vol = annual_volatility / np.sqrt(12.0)
    return monthly_mean, monthly_vol


def simulate_terminal_values(
    *,
    current_corpus_inr: float,
    monthly_contribution_inr: float,
    years: float,
    expected_annual_return: float,
    annual_volatility: float,
    n_sims: int = _DEFAULT_SIMS,
    seed: int | None = 42,
) -> np.ndarray:
    """Return an array of ``n_sims`` simulated terminal net-worth values.

    Contributions are added at the end of each month. A zero-volatility input
    collapses to the deterministic compounding path (every sim identical).
    """
    if years <= 0:
        raise ValueError("years must be > 0")
    if years > _MAX_YEARS:
        raise ValueError(f"years must be <= {_MAX_YEARS}")
    if annual_volatility < 0:
        raise ValueError("annual_volatility must be >= 0")
    if n_sims < 1:
        raise ValueError("n_sims must be >= 1")

    n_months = int(round(years * 12))
    monthly_mean, monthly_vol = _monthly_params(expected_annual_return, annual_volatility)

    rng = np.random.default_rng(seed)
    value = np.full(n_sims, float(current_corpus_inr), dtype=float)
    for _ in range(n_months):
        shocks = rng.normal(monthly_mean, monthly_vol, size=n_sims)
        value = value * (1.0 + shocks) + monthly_contribution_inr
        # A portfolio can't go below zero net worth in this model (no leverage).
        np.clip(value, 0.0, None, out=value)
    return value


def project_goal(
    *,
    current_corpus_inr: float,
    monthly_contribution_inr: float,
    years: float,
    expected_annual_return: float = 0.10,
    annual_volatility: float = 0.15,
    target_inr: float | None = None,
    n_sims: int = _DEFAULT_SIMS,
    seed: int | None = 42,
) -> GoalProjection:
    """Project the terminal net-worth distribution for a savings plan.

    Args:
        current_corpus_inr: starting net worth.
        monthly_contribution_inr: amount added every month (e.g. a SIP).
        years: horizon.
        expected_annual_return: mean nominal annual return (e.g. 0.10 = 10%).
        annual_volatility: annual standard deviation of returns.
        target_inr: optional goal; if set, the result carries P(reach target).
        n_sims / seed: Monte Carlo controls (seeded ⇒ deterministic).
    """
    terminals = simulate_terminal_values(
        current_corpus_inr=current_corpus_inr,
        monthly_contribution_inr=monthly_contribution_inr,
        years=years,
        expected_annual_return=expected_annual_return,
        annual_volatility=annual_volatility,
        n_sims=n_sims,
        seed=seed,
    )
    n_months = int(round(years * 12))
    pct = np.percentile(terminals, [10, 25, 50, 75, 90])
    prob = None
    if target_inr is not None:
        prob = float(np.mean(terminals >= target_inr))

    return GoalProjection(
        years=float(years),
        n_months=n_months,
        current_corpus_inr=float(current_corpus_inr),
        monthly_contribution_inr=float(monthly_contribution_inr),
        expected_annual_return=float(expected_annual_return),
        annual_volatility=float(annual_volatility),
        total_contributed_inr=float(monthly_contribution_inr) * n_months,
        p10=float(pct[0]),
        p25=float(pct[1]),
        p50=float(pct[2]),
        p75=float(pct[3]),
        p90=float(pct[4]),
        mean=float(np.mean(terminals)),
        target_inr=None if target_inr is None else float(target_inr),
        probability_of_target=prob,
    )


def required_monthly_contribution(
    *,
    current_corpus_inr: float,
    target_inr: float,
    years: float,
    expected_annual_return: float = 0.10,
    annual_volatility: float = 0.15,
    n_sims: int = _DEFAULT_SIMS,
    seed: int | None = 42,
    tol_inr: float = 1.0,
    max_iter: int = 60,
) -> float:
    """Solve for the monthly contribution whose *median* terminal value hits target.

    The median terminal value is monotone increasing in the contribution, so a
    bisection converges. Returns 0.0 when the current corpus already reaches the
    target at the median with no further contributions.
    """
    if years <= 0:
        raise ValueError("years must be > 0")

    def median_terminal(contribution: float) -> float:
        terminals = simulate_terminal_values(
            current_corpus_inr=current_corpus_inr,
            monthly_contribution_inr=contribution,
            years=years,
            expected_annual_return=expected_annual_return,
            annual_volatility=annual_volatility,
            n_sims=n_sims,
            seed=seed,
        )
        return float(np.percentile(terminals, 50))

    # Already there with no contributions?
    if median_terminal(0.0) >= target_inr:
        return 0.0

    # Find an upper bound that overshoots the target.
    lo, hi = 0.0, max(1000.0, target_inr / max(years * 12, 1))
    for _ in range(40):
        if median_terminal(hi) >= target_inr:
            break
        hi *= 2.0
    else:
        # Couldn't bracket — return the last (very large) guess rather than loop.
        return float(hi)

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        m = median_terminal(mid)
        if abs(m - target_inr) <= tol_inr * max(1.0, target_inr / 1e6):
            return float(mid)
        if m < target_inr:
            lo = mid
        else:
            hi = mid
    return float((lo + hi) / 2.0)


__all__ = [
    "GoalProjection",
    "simulate_terminal_values",
    "project_goal",
    "required_monthly_contribution",
]
