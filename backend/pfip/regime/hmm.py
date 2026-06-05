"""Spec-named alias for the HMM regime detector.

The original implementation lives in :mod:`pfip.regime.hmm_detector`. This
module re-exports it under the name called out in the build spec so callers can
``from pfip.regime.hmm import HMMRegimeDetector`` directly.

It also exposes a 3-state convenience constructor (``build_three_state``) for
markets that prefer the bull/bear/sideways trichotomy from the spec.
"""

from __future__ import annotations

from pfip.regime.hmm_detector import (  # noqa: F401  re-exports
    HMMRegimeDetector,
    RegimePrediction,
)


def build_three_state(*, random_state: int = 42) -> HMMRegimeDetector:
    """Return a 3-state HMM detector (bull / bear / sideways)."""
    return HMMRegimeDetector(
        n_states=3,
        covariance_type="diag",
        n_iter=200,
        random_state=random_state,
    )


def build_four_state(*, random_state: int = 42) -> HMMRegimeDetector:
    """Return a 4-state HMM detector (adds HIGH_VOLATILITY bucket)."""
    return HMMRegimeDetector(
        n_states=4,
        covariance_type="diag",
        n_iter=200,
        random_state=random_state,
    )
