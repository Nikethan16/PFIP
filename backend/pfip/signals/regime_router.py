"""Hand-coded regime → model mapping (plan Section 7.2).

At Stage 4 we dispatch on the current regime to a specialist model. All of
these start life as the same ``LGBMBaselineModel`` with different
hyperparameters; the plan's auto-selector replaces this at Stage 6+.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from pfip.core.contracts import Regime
from pfip.signals.lgbm_baseline import LGBMBaselineModel

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default model factory per regime
# ---------------------------------------------------------------------------


def _trend_specialist() -> LGBMBaselineModel:
    """Longer horizon, higher buy threshold — trend-following flavour."""
    return LGBMBaselineModel(
        model_name="lgbm_trend",
        model_version="0.1.0",
        horizon=3,
        buy_threshold=0.58,
        sell_threshold=0.42,
    )


def _bear_specialist() -> LGBMBaselineModel:
    """Same features, bear-regime tuning — biases towards SELL/HOLD."""
    return LGBMBaselineModel(
        model_name="lgbm_bear",
        model_version="0.1.0",
        horizon=3,
        buy_threshold=0.62,
        sell_threshold=0.45,
    )


def _meanrev_specialist() -> LGBMBaselineModel:
    """Mean-reversion tuning for sideways regimes."""
    return LGBMBaselineModel(
        model_name="lgbm_meanrev",
        model_version="0.1.0",
        horizon=3,
        buy_threshold=0.53,
        sell_threshold=0.47,
    )


def _vol_specialist() -> LGBMBaselineModel:
    """High-vol regime: raise thresholds to tamp noise; shorter horizon."""
    return LGBMBaselineModel(
        model_name="lgbm_highvol",
        model_version="0.1.0",
        horizon=2,
        buy_threshold=0.60,
        sell_threshold=0.40,
        confidence_floor=75,
    )


ROUTE_MAP: dict[Regime, Callable[[], LGBMBaselineModel]] = {
    Regime.BULL_TREND: _trend_specialist,
    Regime.BEAR_TREND: _bear_specialist,
    Regime.SIDEWAYS: _meanrev_specialist,
    Regime.HIGH_VOLATILITY: _vol_specialist,
    # Unmapped regimes fall back to the trend specialist (still a baseline).
    Regime.ACCUMULATION: _meanrev_specialist,
    Regime.DISTRIBUTION: _bear_specialist,
}


def route_for_regime(regime: Regime) -> LGBMBaselineModel:
    """Return a fresh model instance for the given regime."""
    factory = ROUTE_MAP.get(regime, _trend_specialist)
    return factory()


@dataclass
class RegimeRouter:
    """Light container + accessor with a cache so we don't re-instantiate per call.

    Instances are *unfitted*; the caller is responsible for fitting on the
    right slice of history before predicting.
    """

    _cache: dict[Regime, LGBMBaselineModel] | None = None

    def __post_init__(self) -> None:
        if self._cache is None:
            self._cache = {}

    def get(self, regime: Regime) -> LGBMBaselineModel:
        assert self._cache is not None
        if regime not in self._cache:
            self._cache[regime] = route_for_regime(regime)
        return self._cache[regime]

    def reset(self) -> None:
        assert self._cache is not None
        self._cache.clear()
