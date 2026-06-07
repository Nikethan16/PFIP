"""Strategic + tactical allocation engine.

Per plan Section 2.1:
    - Strategic targets are the long-term policy (equity/debt/gold/crypto %).
    - Tactical adjustments tilt around strategic based on regime + sentiment.
    - Rebalance suggestions fire when drift exceeds a threshold.

All outputs are advisory. Never auto-executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pfip.tax.indian_rules import DISCLAIMER


# ---------------------------------------------------------------------------
# Strategic
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategicTargets:
    """Policy allocation (sums to 1.0)."""

    equity_pct: float = 0.50
    debt_pct: float = 0.25
    gold_pct: float = 0.10
    crypto_pct: float = 0.10
    cash_pct: float = 0.05

    def validate(self) -> None:
        total = self.equity_pct + self.debt_pct + self.gold_pct + self.crypto_pct + self.cash_pct
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"StrategicTargets must sum to 1.0, got {total}")

    def to_dict(self) -> dict[str, float]:
        return {
            "equity": self.equity_pct,
            "debt": self.debt_pct,
            "gold": self.gold_pct,
            "crypto": self.crypto_pct,
            "cash": self.cash_pct,
        }


# ---------------------------------------------------------------------------
# Tactical
# ---------------------------------------------------------------------------


def _tilt_for_regime(regime: str | None) -> dict[str, float]:
    """Return an additive tilt on top of strategic weights for a regime."""
    if regime is None:
        return {}
    r = regime.lower()
    if r in ("bull_trend",):
        return {"equity": +0.05, "crypto": +0.02, "cash": -0.03, "gold": -0.02, "debt": -0.02}
    if r in ("bear_trend",):
        return {"equity": -0.08, "crypto": -0.05, "cash": +0.06, "gold": +0.04, "debt": +0.03}
    if r in ("high_volatility", "distribution"):
        return {"equity": -0.04, "crypto": -0.04, "cash": +0.04, "gold": +0.02, "debt": +0.02}
    if r in ("accumulation",):
        return {"equity": +0.03, "crypto": +0.02, "cash": -0.03, "debt": -0.02, "gold": 0.0}
    # sideways / unknown
    return {}


def _tilt_for_sentiment(sentiment: float | None) -> dict[str, float]:
    """Sentiment ∈ [-1, 1]: positive → +equity/crypto, negative → +cash/gold."""
    if sentiment is None:
        return {}
    s = max(-1.0, min(1.0, float(sentiment)))
    return {
        "equity": 0.02 * s,
        "crypto": 0.01 * s,
        "cash": -0.02 * s,
        "gold": -0.01 * s,
    }


def tactical_adjust(
    strategic: StrategicTargets,
    regime_per_market: dict[str, str] | None = None,
    signal_sentiment: float | None = None,
    *,
    max_tilt: float = 0.10,
) -> dict[str, float]:
    """Combine regime + sentiment tilts on top of strategic weights.

    Args:
        strategic: policy allocation.
        regime_per_market: e.g. ``{"equity": "bull_trend", "crypto": "bear_trend"}``.
            We use the *equity* regime as the primary driver; crypto regime
            tweaks the crypto bucket.
        signal_sentiment: aggregate news/social sentiment score in [-1, 1].
        max_tilt: cap the sum of absolute tilts (defensive against big swings).

    Returns:
        Adjusted mapping bucket → percentage (sums to 1.0).
    """
    strategic.validate()
    base = strategic.to_dict()

    tilt: dict[str, float] = {k: 0.0 for k in base}
    rpm = regime_per_market or {}
    for t in (_tilt_for_regime(rpm.get("equity")), _tilt_for_sentiment(signal_sentiment)):
        for k, v in t.items():
            tilt[k] = tilt.get(k, 0.0) + v
    # crypto regime overlays only crypto
    crypto_tilt = _tilt_for_regime(rpm.get("crypto"))
    if "crypto" in crypto_tilt:
        tilt["crypto"] = tilt.get("crypto", 0.0) + crypto_tilt["crypto"] * 0.5

    # cap total absolute tilt
    mag = sum(abs(v) for v in tilt.values())
    if mag > max_tilt:
        scale = max_tilt / mag
        tilt = {k: v * scale for k, v in tilt.items()}

    adjusted = {k: max(0.0, base.get(k, 0.0) + tilt.get(k, 0.0)) for k in base}
    # re-normalise
    total = sum(adjusted.values())
    if total > 0:
        adjusted = {k: v / total for k, v in adjusted.items()}
    return adjusted


# ---------------------------------------------------------------------------
# Rebalance suggestions
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RebalanceSuggestion:
    """Advisory trade to pull a bucket back toward target."""

    bucket: str
    action: str  # BUY / SELL
    drift: float
    current_pct: float
    target_pct: float
    notional_inr: Decimal
    rationale: str


def rebalance_suggestions(
    current_allocation: dict[str, Decimal],
    target_allocation: dict[str, float],
    drift_threshold: float = 0.05,
) -> list[RebalanceSuggestion]:
    """Suggest trades when any bucket's drift > ``drift_threshold``.

    Args:
        current_allocation: bucket → INR value.
        target_allocation: bucket → target weight (sum 1.0).
        drift_threshold: absolute percentage-point drift that triggers a trade.

    Returns:
        List of suggestions. Empty list = nothing to do.
    """
    total = sum(Decimal(str(v)) for v in current_allocation.values())
    if total <= 0:
        return []
    out: list[RebalanceSuggestion] = []
    for bucket, target_pct in target_allocation.items():
        current_value = Decimal(str(current_allocation.get(bucket, 0)))
        current_pct = float(current_value / total)
        drift = current_pct - target_pct
        if abs(drift) < drift_threshold:
            continue
        target_value = (total * Decimal(str(target_pct))).quantize(Decimal("0.01"))
        notional = abs(target_value - current_value).quantize(Decimal("0.01"))
        action = "SELL" if drift > 0 else "BUY"
        out.append(
            RebalanceSuggestion(
                bucket=bucket,
                action=action,
                drift=drift,
                current_pct=current_pct,
                target_pct=target_pct,
                notional_inr=notional,
                rationale=(
                    f"{bucket} drift {drift:+.1%} exceeds {drift_threshold:.0%}; "
                    f"{action} ₹{notional} to realign."
                ),
            )
        )
    return sorted(out, key=lambda s: abs(s.drift), reverse=True)


def suggestions_to_dict(suggestions: list[RebalanceSuggestion]) -> dict:
    """API-ready dict wrapper with disclaimer."""
    return {
        "suggestions": [
            {
                "bucket": s.bucket,
                "action": s.action,
                "drift": s.drift,
                "current_pct": s.current_pct,
                "target_pct": s.target_pct,
                "notional_inr": str(s.notional_inr),
                "rationale": s.rationale,
            }
            for s in suggestions
        ],
        "disclaimer": DISCLAIMER,
    }
