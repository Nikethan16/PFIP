"""Volatility analytics — the realized-vol cone (F2).

The signals model forecasts daily *direction* and has no demonstrated edge
(all HOLD, ~0.46 OOS). Volatility has far more structure, so this surfaces a
classic **vol cone**: for several horizons, the current realized volatility
against the historical distribution (p10/p50/p90) of that same horizon's
realized vol. Pure + unit-tested; the training-based forecaster lives in
``pfip.vol.cone`` (Chronos/GARCH) and is complementary.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel

_TRADING_DAYS = 252
DEFAULT_WINDOWS = (21, 63, 126, 252)


class ConeBucket(BaseModel):
    window_days: int
    current: Optional[float] = None  # latest realized vol for this horizon
    p10: Optional[float] = None
    p50: Optional[float] = None
    p90: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    percentile: Optional[float] = None  # where `current` sits in the history (0..100)


def _log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


def _std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def _annualized_vol(returns: list[float]) -> float:
    return _std(returns) * math.sqrt(_TRADING_DAYS)


def _percentile(sorted_vals: list[float], q: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q / 100.0 * (len(sorted_vals) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _rank_percentile(sorted_vals: list[float], value: float) -> Optional[float]:
    if not sorted_vals:
        return None
    below = sum(1 for v in sorted_vals if v <= value)
    return round(below / len(sorted_vals) * 100.0, 1)


def vol_cone(closes: list[float], windows: tuple[int, ...] = DEFAULT_WINDOWS) -> list[ConeBucket]:
    """Realized-vol cone: current vs historical distribution, per horizon."""
    returns = _log_returns(closes)
    buckets: list[ConeBucket] = []
    for w in windows:
        # Rolling annualized realized vol over each window of `w` returns.
        series: list[float] = []
        if len(returns) >= w:
            for i in range(w, len(returns) + 1):
                series.append(_annualized_vol(returns[i - w : i]))
        if not series:
            buckets.append(ConeBucket(window_days=w))
            continue
        current = series[-1]
        srt = sorted(series)
        buckets.append(
            ConeBucket(
                window_days=w,
                current=round(current, 4),
                p10=round(_percentile(srt, 10) or 0.0, 4),
                p50=round(_percentile(srt, 50) or 0.0, 4),
                p90=round(_percentile(srt, 90) or 0.0, 4),
                min=round(srt[0], 4),
                max=round(srt[-1], 4),
                percentile=_rank_percentile(srt, current),
            )
        )
    return buckets
