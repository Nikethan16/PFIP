"""Change-point detection for regimes (the ``ruptures`` baseline).

This is the third regime view, run *alongside* the HMM (``hmm_detector.py``) and
the Markov-switching model (``markov_switching.py``). Where those two assign
every bar to a latent state, change-point detection answers a different,
complementary question: **when did the statistical behaviour of returns
actually break?** A fresh change point on the most recent bars is an early
warning that the HMM/MS labels are about to move — useful as a regime-stability
feature and as an alert trigger.

Design mirrors the other two detectors:
  * optional heavy dep (``ruptures``) with a dependency-free fallback
    (deterministic L2 binary segmentation with a BIC-style penalty);
  * a frozen result dataclass;
  * a ``fit`` → introspect trio (``breakpoints`` / ``summary``).

The fallback is not as sharp as PELT/rbf but is deterministic, fast, and good
enough to flag the large mean/variance breaks that matter for regime work, so
the module degrades gracefully on a box without ``ruptures`` installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only when the optional dep is present
    import ruptures as rpt  # type: ignore[import-untyped]

    _RUPTURES_OK = True
except Exception as exc:  # pragma: no cover
    log.info("ruptures unavailable (%s); using L2 binary-segmentation fallback", exc)
    rpt = None  # type: ignore[assignment]
    _RUPTURES_OK = False

_MIN_OBS = 30
_MIN_SEGMENT = 10  # don't split into segments shorter than this


@dataclass(frozen=True)
class ChangePointResult:
    """Outcome of change-point detection on a return series."""

    breakpoints: list[int]  # interior break indices into the return series
    n_changepoints: int
    last_change_index: int | None  # index of the most recent break, or None
    last_change_at: datetime | None  # timestamp of that break, when a time index exists
    days_since_change: int | None  # calendar days from last break to last bar
    method: str  # "ruptures_pelt" or "binseg_l2_fallback"


# ---------------------------------------------------------------------------
# Fallback: deterministic L2 binary segmentation
# ---------------------------------------------------------------------------


def _segment_cost(x: np.ndarray) -> float:
    """L2 cost of a segment = sum of squared deviations from its mean."""
    if x.size == 0:
        return 0.0
    return float(((x - x.mean()) ** 2).sum())


def _binseg_l2(x: np.ndarray, penalty: float, min_size: int = _MIN_SEGMENT) -> list[int]:
    """Greedy binary segmentation with an additive per-breakpoint penalty.

    Repeatedly splits the segment whose split yields the largest cost reduction,
    accepting a split only while the reduction exceeds ``penalty``. Returns the
    sorted interior break indices (not including 0 or ``len(x)``).
    """
    n = x.size
    breaks: list[int] = []
    # Each candidate segment is a [start, end) half-open interval.
    segments: list[tuple[int, int]] = [(0, n)]

    while True:
        best_gain = penalty
        best_split: tuple[int, int, int] | None = None  # (start, split, end)
        for start, end in segments:
            if end - start < 2 * min_size:
                continue
            base = _segment_cost(x[start:end])
            # Try every admissible split point in this segment.
            for split in range(start + min_size, end - min_size + 1):
                gain = base - _segment_cost(x[start:split]) - _segment_cost(x[split:end])
                if gain > best_gain:
                    best_gain = gain
                    best_split = (start, split, end)
        if best_split is None:
            break
        start, split, end = best_split
        breaks.append(split)
        segments.remove((start, end))
        segments.extend([(start, split), (split, end)])

    return sorted(breaks)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class ChangePointDetector:
    """Detect structural breaks in a price series' log-returns.

    Args:
        penalty: break penalty. With ``ruptures`` this is the PELT ``pen``; with
            the fallback it's the minimum L2 cost reduction required to accept a
            split. Larger ⇒ fewer breaks. ``None`` ⇒ a BIC-style default
            (``log(n) * variance``) so the sensitivity scales with the data.
        min_size: shortest admissible segment length.
    """

    def __init__(self, *, penalty: float | None = None, min_size: int = _MIN_SEGMENT) -> None:
        self.penalty = penalty
        self.min_size = min_size
        self._result: ChangePointResult | None = None

    @staticmethod
    def _log_returns(prices: pd.Series) -> pd.Series:
        r = np.log(prices / prices.shift(1)).dropna()
        return r.replace([np.inf, -np.inf], np.nan).dropna()

    def _resolve_penalty(self, x: np.ndarray) -> float:
        if self.penalty is not None:
            return float(self.penalty)
        # BIC-style: scales with series length and noise level.
        var = float(np.var(x)) or 1e-8
        return float(np.log(max(x.size, 2)) * var)

    def fit(self, prices: pd.Series) -> "ChangePointDetector":
        returns = self._log_returns(prices)
        index = returns.index
        x = returns.to_numpy(dtype=float)

        if x.size < _MIN_OBS:
            self._result = ChangePointResult(
                breakpoints=[],
                n_changepoints=0,
                last_change_index=None,
                last_change_at=None,
                days_since_change=None,
                method="binseg_l2_fallback",
            )
            return self

        penalty = self._resolve_penalty(x)
        if _RUPTURES_OK:
            method = "ruptures_pelt"
            try:  # pragma: no cover - requires the optional dep
                algo = rpt.Pelt(model="rbf", min_size=self.min_size).fit(x)
                # ruptures returns segment ends including the final endpoint.
                raw = algo.predict(pen=penalty)
                breaks = [b for b in raw if 0 < b < x.size]
            except Exception as exc:  # pragma: no cover
                log.warning("ruptures failed (%s); using fallback", exc)
                method = "binseg_l2_fallback"
                breaks = _binseg_l2(x, penalty, self.min_size)
        else:
            method = "binseg_l2_fallback"
            breaks = _binseg_l2(x, penalty, self.min_size)

        last_idx = breaks[-1] if breaks else None
        last_at: datetime | None = None
        days_since: int | None = None
        if last_idx is not None and last_idx < len(index):
            ts = index[last_idx]
            last_at = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
            end_ts = index[-1]
            if last_at is not None and hasattr(end_ts, "to_pydatetime"):
                days_since = int((end_ts.to_pydatetime() - last_at).days)

        self._result = ChangePointResult(
            breakpoints=breaks,
            n_changepoints=len(breaks),
            last_change_index=last_idx,
            last_change_at=last_at,
            days_since_change=days_since,
            method=method,
        )
        return self

    def result(self) -> ChangePointResult:
        if self._result is None:
            raise RuntimeError("call fit(prices) first")
        return self._result


def detect_change_points(
    prices: pd.Series, *, penalty: float | None = None, min_size: int = _MIN_SEGMENT
) -> ChangePointResult:
    """Convenience one-shot wrapper around :class:`ChangePointDetector`."""
    return ChangePointDetector(penalty=penalty, min_size=min_size).fit(prices).result()


__all__ = ["ChangePointDetector", "ChangePointResult", "detect_change_points"]
