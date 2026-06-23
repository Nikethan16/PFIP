"""SIP (Systematic Investment Plan) tracking — XIRR + corpus projection.

Indian investors live in SIPs: fixed monthly contributions into funds. The two
things they actually want to know are:

  1. **XIRR** — the annualised internal rate of return over irregular cash
     flows (every SIP instalment is a separate-dated outflow; the current value
     is one inflow). Computed here with Newton's method and a bisection
     fallback, so it converges even on awkward flows.
  2. **Projected corpus** — what a recurring monthly SIP grows to at an assumed
     annual return (future-value of an annuity, compounded monthly).

All functions are pure; no DB needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class CashFlow:
    """A dated cash flow. Negative = money out (investment), positive = money in."""

    when: date
    amount: float


def _xnpv(rate: float, flows: Sequence[CashFlow]) -> float:
    """Net present value of dated flows at annual ``rate`` (XIRR convention)."""
    t0 = flows[0].when
    return sum(
        cf.amount / ((1.0 + rate) ** ((cf.when - t0).days / _DAYS_PER_YEAR)) for cf in flows
    )


def _xnpv_derivative(rate: float, flows: Sequence[CashFlow]) -> float:
    t0 = flows[0].when
    d = 0.0
    for cf in flows:
        years = (cf.when - t0).days / _DAYS_PER_YEAR
        d -= years * cf.amount / ((1.0 + rate) ** (years + 1.0))
    return d


def xirr(flows: Sequence[CashFlow], *, guess: float = 0.1) -> float | None:
    """Annualised internal rate of return over irregular, dated cash flows.

    Returns ``None`` when there is no sign change (all in or all out ⇒ no IRR)
    or the solver fails to converge. Tries Newton first, then bisection over a
    wide bracket for robustness.
    """
    flows = sorted(flows, key=lambda c: c.when)
    if len(flows) < 2:
        return None
    signs = {c.amount > 0 for c in flows if c.amount != 0}
    if len(signs) < 2:
        return None  # need at least one inflow and one outflow

    # Newton's method.
    rate = guess
    for _ in range(100):
        npv = _xnpv(rate, flows)
        if abs(npv) < 1e-7:
            return rate
        deriv = _xnpv_derivative(rate, flows)
        if deriv == 0:
            break
        new_rate = rate - npv / deriv
        if new_rate <= -0.9999:  # keep (1+rate) positive
            new_rate = (rate - 0.9999) / 2
        if abs(new_rate - rate) < 1e-9:
            return new_rate
        rate = new_rate

    # Bisection fallback over a wide bracket.
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = _xnpv(lo, flows), _xnpv(hi, flows)
    if f_lo * f_hi > 0:
        return None  # no root bracketed
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = _xnpv(mid, flows)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def project_sip_corpus(
    *,
    monthly_amount: float,
    years: float,
    annual_return: float,
    current_corpus: float = 0.0,
) -> dict[str, float]:
    """Future value of a monthly SIP (annuity-due-style: invested at month start).

    Returns the projected corpus, total invested, and the gain.
    """
    if years < 0:
        raise ValueError("years must be >= 0")
    n = int(round(years * 12))
    r = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
    # Grow the existing corpus.
    fv = current_corpus * ((1.0 + r) ** n)
    # Future value of each instalment, invested at the start of its month.
    if abs(r) < 1e-12:
        fv += monthly_amount * n
    else:
        fv += monthly_amount * (((1.0 + r) ** n - 1.0) / r) * (1.0 + r)
    invested = current_corpus + monthly_amount * n
    return {
        "projected_corpus_inr": round(fv, 2),
        "total_invested_inr": round(invested, 2),
        "gain_inr": round(fv - invested, 2),
        "months": n,
    }


def sip_summary(
    instalments: Sequence[CashFlow],
    *,
    current_value: float,
    as_of: date | None = None,
) -> dict[str, float | None]:
    """Summarise a SIP: total invested + realised XIRR to ``current_value``.

    ``instalments`` are the (dated, negative) contribution flows; the current
    portfolio value is appended as a final positive inflow for the XIRR.
    """
    invested = -sum(c.amount for c in instalments if c.amount < 0)
    flows = list(instalments)
    last_date = as_of or (max(c.when for c in flows) if flows else None)
    if last_date is not None and current_value:
        flows = flows + [CashFlow(last_date, current_value)]
    rate = xirr(flows) if len(flows) >= 2 else None
    return {
        "total_invested_inr": round(invested, 2),
        "current_value_inr": round(current_value, 2),
        "absolute_gain_inr": round(current_value - invested, 2),
        "xirr": None if rate is None else round(rate, 6),
        "n_instalments": len([c for c in instalments if c.amount < 0]),
    }


__all__ = ["CashFlow", "xirr", "project_sip_corpus", "sip_summary"]
