"""User-defined alert rules — pure evaluation engine.

A rule is a small declarative condition on a symbol (price above/below a level,
or a 1-day move beyond a threshold). :func:`evaluate_rule` is a pure function
over a price snapshot, so it's unit-testable without a DB or network. The API
layer fetches the snapshot; a future scheduled job can reuse the same engine to
fire Telegram/bell alerts (that needs a rules table + is a logged follow-up).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

AlertRuleKind = Literal["price_above", "price_below", "pct_up_1d", "pct_down_1d"]

RULE_LABELS: dict[AlertRuleKind, str] = {
    "price_above": "Price above",
    "price_below": "Price below",
    "pct_up_1d": "Up ≥ (1d %)",
    "pct_down_1d": "Down ≥ (1d %)",
}


class AlertRule(BaseModel):
    id: Optional[str] = None  # client-assigned; opaque to the backend
    symbol: str
    kind: AlertRuleKind
    threshold: float
    note: Optional[str] = None


class AlertEval(BaseModel):
    rule: AlertRule
    triggered: bool
    current_value: Optional[float] = None  # last close, or 1d move %, per kind
    observed: str  # human phrase, e.g. "last close 187.20"
    reason: str  # why triggered / not / not evaluable


def evaluate_rule(
    rule: AlertRule,
    *,
    last_close: Optional[float],
    move_pct_1d: Optional[float],
) -> AlertEval:
    """Evaluate one rule against a price snapshot for its symbol."""
    if rule.kind in ("price_above", "price_below"):
        if last_close is None:
            return AlertEval(
                rule=rule,
                triggered=False,
                current_value=None,
                observed="no price",
                reason="No recent close for this symbol.",
            )
        above = rule.kind == "price_above"
        triggered = last_close > rule.threshold if above else last_close < rule.threshold
        return AlertEval(
            rule=rule,
            triggered=triggered,
            current_value=round(last_close, 4),
            observed=f"last close {last_close:.2f}",
            reason=(
                f"{last_close:.2f} {'>' if above else '<'} {rule.threshold:.2f}"
                if triggered
                else f"{last_close:.2f} not {'above' if above else 'below'} {rule.threshold:.2f}"
            ),
        )

    # pct_up_1d / pct_down_1d
    if move_pct_1d is None:
        return AlertEval(
            rule=rule,
            triggered=False,
            current_value=None,
            observed="no 1d move",
            reason="Not enough price history for a 1-day move.",
        )
    up = rule.kind == "pct_up_1d"
    thr = abs(rule.threshold)
    triggered = move_pct_1d >= thr if up else move_pct_1d <= -thr
    return AlertEval(
        rule=rule,
        triggered=triggered,
        current_value=round(move_pct_1d, 2),
        observed=f"1d move {move_pct_1d:+.2f}%",
        reason=(
            f"{move_pct_1d:+.2f}% {'≥' if up else '≤'} {'+' if up else '-'}{thr:.2f}%"
            if triggered
            else f"{move_pct_1d:+.2f}% has not {'risen' if up else 'fallen'} {thr:.2f}%"
        ),
    )
