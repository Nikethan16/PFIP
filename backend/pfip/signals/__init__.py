"""ML signal layer — Stage 4 baseline.

Exports:
    LGBMBaselineModel    — LightGBM 3-day classifier with SHAP drivers.
    regime_router         — hand-coded regime → model mapping.
"""

from pfip.signals.lgbm_baseline import (  # noqa: F401
    FEATURE_COLUMNS,
    LGBMBaselineModel,
    SignalOutput,
    make_label,
)
from pfip.signals.regime_router import RegimeRouter, route_for_regime  # noqa: F401
