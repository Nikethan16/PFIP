"""Volatility cone — a data-driven vol prior for the Goals / stress Monte-Carlo.

Per ``docs/ML_SIGNAL_RESEARCH.md`` recommendation #2: use a probabilistic
time-series forecast as a **scenario / volatility prior** (never for directional
signals). Chronos-Bolt is the chosen model, added as an **optional dependency**
that no-ops if absent — mirroring the existing ``ruptures`` / ``lightgbm``
soft-import pattern.

Fallback chain (so this is useful immediately and better with the model):

1. **Chronos-Bolt** (if ``chronos`` + ``torch`` are installed) — quantile forecast
   of forward returns; annualised vol implied from the predicted spread.
2. **Historical** — realised annualised vol from the price series. Always
   available; already a strict improvement over a flat hand-entered guess.
3. **None** — not enough data; caller keeps its own default.

Installing the model later (``pip install 'chronos-forecasting' torch``) upgrades
every caller from the historical prior to the model prior with no code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

_TRADING_DAYS = 252
_MIN_OBS = 40

# Lazy soft-import singleton. False = tried and unavailable; None = not tried.
_pipeline: Any = None


def _load_chronos() -> Any | None:
    """Load Chronos-Bolt once; return None if the optional deps aren't installed."""
    global _pipeline
    if _pipeline is None:
        try:  # optional dependency — absence is a no-op
            import torch  # noqa: F401
            from chronos import BaseChronosPipeline

            _pipeline = BaseChronosPipeline.from_pretrained("amazon/chronos-bolt-small")
        except Exception:  # — any import/load failure → dormant
            _pipeline = False
    return _pipeline or None


def chronos_available() -> bool:
    """True iff Chronos-Bolt (torch + chronos) is installed and loadable."""
    return _load_chronos() is not None


@dataclass(frozen=True, slots=True)
class VolCone:
    """A forward volatility estimate + its provenance."""

    annual_vol: float
    horizon_days: int
    source: str  # "chronos" | "historical"

    def as_dict(self) -> dict[str, Any]:
        return {
            "annual_vol": round(self.annual_vol, 4),
            "horizon_days": self.horizon_days,
            "source": self.source,
        }


def _log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices.astype(float) / prices.astype(float).shift(1)).dropna()


def historical_annual_vol(prices: pd.Series) -> float | None:
    """Realised annualised vol from a daily price series. None if too short."""
    r = _log_returns(prices)
    if len(r) < _MIN_OBS:
        return None
    return float(r.std(ddof=1) * np.sqrt(_TRADING_DAYS))


def _chronos_annual_vol(prices: pd.Series, horizon_days: int) -> float | None:
    """Chronos-Bolt implied forward vol; None if the model isn't installed."""
    pipe = _load_chronos()
    if pipe is None:
        return None
    try:
        import torch

        r = _log_returns(prices)
        if len(r) < _MIN_OBS:
            return None
        ctx = torch.tensor(r.to_numpy(), dtype=torch.float32)
        # Quantile forecast of forward daily log-returns.
        q, _ = pipe.predict_quantiles(
            context=ctx,
            prediction_length=max(1, horizon_days),
            quantile_levels=[0.1, 0.5, 0.9],
        )
        # q shape: [batch, horizon, n_quantiles]; take the first series.
        band = q[0]  # [horizon, 3] -> columns q10,q50,q90
        q10 = band[:, 0].numpy()
        q90 = band[:, 2].numpy()
        # Per-step implied sigma from the 10-90 band (z=1.2816 each side).
        per_step_sigma = float(np.mean((q90 - q10) / (2.0 * 1.2816)))
        return per_step_sigma * np.sqrt(_TRADING_DAYS)
    except Exception:  # — never let the model path break the caller
        return None


def forecast_vol_cone(prices: pd.Series, *, horizon_days: int = 252) -> VolCone | None:
    """Best-available forward annual vol: Chronos → historical → None.

    ``prices`` is a daily close series (index ascending). Returns ``None`` only
    when there isn't enough data for even the historical estimate, so callers can
    fall back to their own default.
    """
    if prices is None or len(prices) < _MIN_OBS:
        return None
    chronos = _chronos_annual_vol(prices, horizon_days)
    if chronos is not None and np.isfinite(chronos) and chronos > 0:
        return VolCone(annual_vol=chronos, horizon_days=horizon_days, source="chronos")
    hist = historical_annual_vol(prices)
    if hist is not None and np.isfinite(hist) and hist > 0:
        return VolCone(annual_vol=hist, horizon_days=horizon_days, source="historical")
    return None


__all__ = ["VolCone", "chronos_available", "forecast_vol_cone", "historical_annual_vol"]
