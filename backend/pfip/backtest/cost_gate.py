"""Cost gate (F4) — judge a strategy on economic value, not hit-rate.

A model that's right 55% of the time can still lose money once you subtract
spread + fees + slippage. This pure helper takes a strategy's per-period gross
returns and its per-period turnover (fraction of book traded), charges a cost
per unit of turnover, and reports the **net** economics against a naive
buy-and-hold baseline. Nothing gets surfaced as a "signal" until it clears this
gate. Pure + unit-tested.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel

_TRADING_DAYS = 252


class CostGateResult(BaseModel):
    gross_total_return: float
    net_total_return: float
    baseline_total_return: float
    net_sharpe: float
    cost_drag: float  # gross_total - net_total
    beats_baseline: bool  # net strategy return > buy-and-hold
    passes: bool  # positive net return AND beats baseline
    cost_bps: float
    n_periods: int


def _total_return(period_returns: list[float]) -> float:
    acc = 1.0
    for r in period_returns:
        acc *= 1.0 + r
    return acc - 1.0


def _sharpe(period_returns: list[float]) -> float:
    n = len(period_returns)
    if n < 2:
        return 0.0
    mean = sum(period_returns) / n
    var = sum((r - mean) ** 2 for r in period_returns) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(_TRADING_DAYS)


def cost_gate(
    gross_returns: list[float],
    turnover: list[float],
    baseline_returns: list[float],
    *,
    cost_bps: float = 10.0,
) -> CostGateResult:
    """Net a strategy after per-turnover costs and compare to a baseline.

    ``gross_returns`` and ``turnover`` are per-period, same length. ``cost_bps``
    is charged per unit of turnover (1.0 turnover = whole book traded).
    ``baseline_returns`` is the buy-and-hold return stream to beat.
    """
    cost = cost_bps / 10_000.0
    net_returns = [
        g - (turnover[i] if i < len(turnover) else 0.0) * cost for i, g in enumerate(gross_returns)
    ]
    gross_total = _total_return(gross_returns)
    net_total = _total_return(net_returns)
    baseline_total = _total_return(baseline_returns)
    beats = net_total > baseline_total
    return CostGateResult(
        gross_total_return=round(gross_total, 6),
        net_total_return=round(net_total, 6),
        baseline_total_return=round(baseline_total, 6),
        net_sharpe=round(_sharpe(net_returns), 4),
        cost_drag=round(gross_total - net_total, 6),
        beats_baseline=beats,
        passes=bool(net_total > 0 and beats),
        cost_bps=cost_bps,
        n_periods=len(gross_returns),
    )
