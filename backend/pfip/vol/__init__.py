"""Volatility forecasting models.

Phase 1 ships the GARCH(1,1) baseline — the bar that any later volatility model
(e.g. the IBM TinyTimeMixer in Phase 3) must beat after costs in the scoring
harness. Forecasts here are *risk features*, never alpha.
"""

from pfip.vol.garch import (
    GarchVolForecaster,
    VolForecast,
    evaluate_vol_forecast,
)

__all__ = [
    "GarchVolForecaster",
    "VolForecast",
    "evaluate_vol_forecast",
]
