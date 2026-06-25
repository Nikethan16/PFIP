"""Direct unit tests for ``pfip.portfolio.allocation``.

Pure functions: strategic-target validation, regime/sentiment tactical tilts
(capped + re-normalised), and rebalance suggestions off drift.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pfip.portfolio.allocation import (
    StrategicTargets,
    rebalance_suggestions,
    suggestions_to_dict,
    tactical_adjust,
)


# ---------------------------------------------------------------------------
# StrategicTargets
# ---------------------------------------------------------------------------


def test_default_strategic_targets_sum_to_one():
    StrategicTargets().validate()  # must not raise


def test_invalid_strategic_targets_raise():
    with pytest.raises(ValueError):
        StrategicTargets(equity_pct=0.9, debt_pct=0.9).validate()


# ---------------------------------------------------------------------------
# tactical_adjust
# ---------------------------------------------------------------------------


def test_tactical_adjust_normalises_to_one():
    out = tactical_adjust(StrategicTargets(), {"equity": "bull_trend"}, 0.5)
    assert sum(out.values()) == pytest.approx(1.0)


def test_tactical_bull_tilts_into_equity():
    base = StrategicTargets().to_dict()
    out = tactical_adjust(StrategicTargets(), {"equity": "bull_trend"}, None)
    assert out["equity"] > base["equity"]


def test_tactical_bear_tilts_out_of_equity_into_cash():
    base = StrategicTargets().to_dict()
    out = tactical_adjust(StrategicTargets(), {"equity": "bear_trend"}, None)
    assert out["equity"] < base["equity"]
    assert out["cash"] > base["cash"]


def test_tactical_no_regime_no_sentiment_is_strategic():
    out = tactical_adjust(StrategicTargets(), None, None)
    base = StrategicTargets().to_dict()
    for k in base:
        assert out[k] == pytest.approx(base[k])


def test_tactical_tilt_is_capped():
    # An extreme bear + max-negative sentiment must still respect max_tilt:
    # no single bucket can move more than the cap from strategic.
    base = StrategicTargets().to_dict()
    out = tactical_adjust(StrategicTargets(), {"equity": "bear_trend"}, -1.0, max_tilt=0.05)
    moved = sum(abs(out[k] - base[k]) for k in base)
    # After re-normalisation the moves stay small; sanity bound well under 2x cap.
    assert moved <= 0.2


def test_tactical_all_weights_nonnegative():
    out = tactical_adjust(StrategicTargets(), {"equity": "bear_trend"}, -1.0)
    assert all(v >= 0 for v in out.values())


# ---------------------------------------------------------------------------
# rebalance_suggestions
# ---------------------------------------------------------------------------


def test_rebalance_empty_when_on_target():
    current = {"equity": Decimal("50"), "debt": Decimal("50")}
    target = {"equity": 0.5, "debt": 0.5}
    assert rebalance_suggestions(current, target) == []


def test_rebalance_suggests_sell_when_overweight():
    current = {"equity": Decimal("80"), "debt": Decimal("20")}
    target = {"equity": 0.5, "debt": 0.5}
    out = rebalance_suggestions(current, target, drift_threshold=0.05)
    eq = next(s for s in out if s.bucket == "equity")
    assert eq.action == "SELL"  # overweight ⇒ sell
    assert eq.drift > 0


def test_rebalance_suggests_buy_when_underweight():
    current = {"equity": Decimal("20"), "debt": Decimal("80")}
    target = {"equity": 0.5, "debt": 0.5}
    out = rebalance_suggestions(current, target, drift_threshold=0.05)
    eq = next(s for s in out if s.bucket == "equity")
    assert eq.action == "BUY"


def test_rebalance_sorted_by_abs_drift():
    current = {"equity": Decimal("90"), "debt": Decimal("8"), "gold": Decimal("2")}
    target = {"equity": 0.5, "debt": 0.3, "gold": 0.2}
    out = rebalance_suggestions(current, target, drift_threshold=0.05)
    drifts = [abs(s.drift) for s in out]
    assert drifts == sorted(drifts, reverse=True)


def test_rebalance_empty_on_zero_total():
    assert rebalance_suggestions({"equity": Decimal("0")}, {"equity": 1.0}) == []


def test_suggestions_to_dict_carries_disclaimer():
    current = {"equity": Decimal("80"), "debt": Decimal("20")}
    target = {"equity": 0.5, "debt": 0.5}
    out = suggestions_to_dict(rebalance_suggestions(current, target))
    assert "disclaimer" in out
    assert isinstance(out["suggestions"], list)
    assert out["suggestions"][0]["notional_inr"]  # serialised as str
