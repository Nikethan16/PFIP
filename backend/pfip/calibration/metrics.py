"""Spec-named alias for the calibration metric primitives.

The original implementation lives in :mod:`pfip.calibration.brier_ece`. This
module re-exports it under the name listed in the build plan so callers can
``from pfip.calibration.metrics import compute_brier_score`` directly.
"""

from __future__ import annotations

from pfip.calibration.brier_ece import (  # noqa: F401
    CalibrationSummary,
    ReliabilityBin,
    check_suspension_rule,
    compute_brier_score,
    compute_ece,
    reliability_diagram,
    sharpness,
)


def summarise(
    y_true,
    y_prob,
    *,
    n_bins: int = 10,
) -> CalibrationSummary:
    """Compute the full :class:`CalibrationSummary` in one call."""
    brier = compute_brier_score(y_true, y_prob)
    ece = compute_ece(y_true, y_prob, n_bins=n_bins)
    rel = reliability_diagram(y_true, y_prob, n_bins=n_bins)
    sharp = sharpness(y_prob)
    return CalibrationSummary(
        brier=brier,
        ece=ece,
        sharpness=sharp,
        reliability=rel,
        n_samples=len(list(y_true)),
    )
