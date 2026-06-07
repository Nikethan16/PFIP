"""Auto-suspension / floor-raising rules per plan §8.4.

Rules:
    R1. If ECE > 0.15 for **two consecutive months**, suspend the model.
    R2. If the 65-confidence-bucket win-rate drops below 55% for **three
        consecutive months**, raise the confidence floor for that model to 75.

These functions are pure — they take history and produce a decision. The
runner is responsible for actually emitting the suspension / floor-raise
event into the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pfip.calibration.brier_ece import check_suspension_rule


@dataclass(frozen=True)
class RuleResult:
    """Decisions from a single rule-evaluation pass."""

    suspend: bool
    raise_floor_to: int | None
    reason: str

    def is_action(self) -> bool:
        return self.suspend or self.raise_floor_to is not None


def evaluate_rules(
    *,
    ece_history: Sequence[float],
    bucket_win_rates: Sequence[float | None],
    ece_threshold: float = 0.15,
    ece_n_consecutive: int = 2,
    bucket_floor_win_rate: float = 0.55,
    bucket_n_consecutive: int = 3,
    raised_floor: int = 75,
) -> RuleResult:
    """Apply R1 + R2 and return the combined :class:`RuleResult`.

    ``ece_history`` is in chronological order (latest at the end).
    ``bucket_win_rates`` is the per-month win-rate of the 65-confidence
    bucket; ``None`` entries are treated as "no data" (rule pauses).
    """
    suspend = check_suspension_rule(
        ece_history, threshold=ece_threshold, n_consecutive=ece_n_consecutive
    )

    # R2: 3 consecutive months of bucket win rate < bucket_floor_win_rate
    raise_floor = False
    cleaned = [v for v in bucket_win_rates if v is not None]
    if len(cleaned) >= bucket_n_consecutive:
        tail = cleaned[-bucket_n_consecutive:]
        raise_floor = all(v < bucket_floor_win_rate for v in tail)

    reasons: list[str] = []
    if suspend:
        reasons.append(f"ECE > {ece_threshold} for {ece_n_consecutive} consecutive months")
    if raise_floor:
        reasons.append(
            f"65-bucket win-rate < {bucket_floor_win_rate:.0%} "
            f"for {bucket_n_consecutive} consecutive months -> floor -> {raised_floor}"
        )
    reason = "; ".join(reasons) if reasons else "all rules pass"

    return RuleResult(
        suspend=suspend,
        raise_floor_to=raised_floor if raise_floor else None,
        reason=reason,
    )
