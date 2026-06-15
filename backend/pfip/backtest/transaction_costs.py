"""Per-market transaction-cost model.

Plan §8.2 cost table:

    Market    Cost (round-trip)
    crypto    10 bps
    us        5 bps
    india     25 bps (STT/STCG eats into this further)

The :func:`apply_costs_to_positions` helper takes a position series (in
``{-1, 0, 1}``) and a bar-return series and returns the *net* return series
after charging the per-trade cost on each position change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

_COST_BPS = {
    "crypto": 10.0,
    "us": 5.0,
    "india": 25.0,
    "fx": 5.0,
}

# India: STT applies to equity delivery (0.1% on each side of an equity sell)
# and STCG/LTCG on realised gains, but neither is a per-trade BPS we can fold
# in cleanly. We bundle a slightly higher BPS to approximate.
_INDIA_STT_BPS = 10.0  # additional 10 bps tacked on for sells


@dataclass(frozen=True)
class CostModel:
    """Bundle of per-market costs in bps."""

    market: str
    per_side_bps: float
    sell_extra_bps: float = 0.0  # e.g. STT for Indian equity

    def per_side(self) -> float:
        return self.per_side_bps

    def round_trip(self) -> float:
        return self.per_side_bps * 2 + self.sell_extra_bps


def cost_model_for(market: str) -> CostModel:
    """Build a :class:`CostModel` for ``crypto`` / ``us`` / ``india`` / ``fx``.

    Unknown markets default to crypto (the most common in PFIP scope).
    """
    m = market.lower()
    if m == "india":
        return CostModel(
            market="india",
            per_side_bps=_COST_BPS["india"],
            sell_extra_bps=_INDIA_STT_BPS,
        )
    if m in _COST_BPS:
        return CostModel(market=m, per_side_bps=_COST_BPS[m])
    return CostModel(market="crypto", per_side_bps=_COST_BPS["crypto"])


def transaction_cost_bps(market: str) -> float:
    """Per-side bps charge — preserves the engine's existing constant API."""
    return cost_model_for(market).per_side_bps


def apply_costs_to_positions(
    positions: pd.Series,
    bar_returns: pd.Series,
    *,
    market: str = "crypto",
) -> pd.Series:
    """Net return after charging round-trip costs whenever the position changes.

    Positions are shifted by 1 (decisions at t affect t+1 return) — same
    convention as :func:`pfip.backtest.vectorbt_engine._apply_strategy`.
    """
    cost = cost_model_for(market)
    pos = positions.reindex(bar_returns.index).fillna(0).astype(float)
    pos_shift = pos.shift(1).fillna(0.0)

    turnover = pos.diff().abs().fillna(pos.abs())
    cost_series = turnover * (cost.per_side_bps / 1e4)
    # Sell-side extra (e.g. STT) only on transitions to a lower position.
    if cost.sell_extra_bps > 0:
        sells = (pos.diff() < 0).astype(float).fillna(0.0)
        cost_series = cost_series + sells * (cost.sell_extra_bps / 1e4)

    return pos_shift * bar_returns - cost_series
