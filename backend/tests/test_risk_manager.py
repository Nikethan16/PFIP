"""Direct unit tests for ``pfip.portfolio.risk_manager``.

The risk manager is the gate every trade passes through, so its logic is
exercised here directly (not just through the API). All inputs are passed
per-call, so no DB or network is needed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pfip.portfolio.risk_manager import RiskManager


@pytest.fixture
def rm() -> RiskManager:
    # Config-only instance (default limits: 10% cap, 20% halt, 2/day).
    return RiskManager()


# ---------------------------------------------------------------------------
# Pre-trade checklist
# ---------------------------------------------------------------------------


def _good_kwargs(**overrides):
    base = dict(
        symbol="RELIANCE.NS",
        qty=Decimal("1"),
        price=Decimal("1000"),
        existing_holdings=[],
        portfolio_value_inr=Decimal("1000000"),
        stop_distance_pct=0.05,
        regime="bull_trend",
        signal_confidence=80,
        news_count_24h=3,
        event_calendar_conflict=False,
        positions_added_today=0,
        current_drawdown_pct=0.0,
    )
    base.update(overrides)
    return base


def test_pre_trade_passes_when_all_green(rm: RiskManager):
    verdict = rm.check_pre_trade(**_good_kwargs())
    assert verdict.pass_all is True
    assert verdict.reasons == []
    assert bool(verdict) is True


def test_pre_trade_fails_without_stop_loss(rm: RiskManager):
    verdict = rm.check_pre_trade(**_good_kwargs(stop_distance_pct=None))
    assert verdict.pass_all is False
    assert verdict.per_item["stop_loss_provided"] is False


def test_pre_trade_fails_when_position_exceeds_cap(rm: RiskManager):
    # 200 units @ 1000 = 200k = 20% of a 1M book > 10% cap.
    verdict = rm.check_pre_trade(**_good_kwargs(qty=Decimal("200")))
    assert verdict.per_item["position_size_within_cap"] is False
    assert any("exceeds cap" in r for r in verdict.reasons)


def test_pre_trade_fails_on_drawdown_halt(rm: RiskManager):
    verdict = rm.check_pre_trade(**_good_kwargs(current_drawdown_pct=0.25))
    assert verdict.per_item["no_drawdown_halt"] is False


def test_pre_trade_fails_when_daily_cap_reached(rm: RiskManager):
    verdict = rm.check_pre_trade(**_good_kwargs(positions_added_today=2))
    assert verdict.per_item["daily_cap_not_reached"] is False


def test_pre_trade_fails_with_unknown_regime(rm: RiskManager):
    verdict = rm.check_pre_trade(**_good_kwargs(regime=None))
    assert verdict.per_item["regime_known"] is False


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


def test_check_drawdown_ok_when_flat(rm: RiskManager):
    status, dd = rm.check_drawdown([Decimal("100"), Decimal("101"), Decimal("100")])
    assert status == "OK"
    assert dd < 0.05


def test_check_drawdown_halts_past_threshold(rm: RiskManager):
    status, dd = rm.check_drawdown([Decimal("100"), Decimal("70")])  # 30% drop
    assert status == "HALT"
    assert dd == pytest.approx(0.30)


def test_check_drawdown_warns_in_between(rm: RiskManager):
    # 12% drop: above 0.5*20%=10% (WARN) but below 20% (HALT).
    status, dd = rm.check_drawdown([100.0, 88.0])
    assert status == "WARN"


def test_check_drawdown_accepts_date_tuples(rm: RiskManager):
    history = [(date(2024, 1, 1), Decimal("100")), (date(2024, 1, 2), Decimal("60"))]
    status, dd = rm.check_drawdown(history)
    assert status == "HALT"
    assert dd == pytest.approx(0.40)


def test_check_drawdown_empty_is_ok(rm: RiskManager):
    assert rm.check_drawdown([]) == ("OK", 0.0)


# ---------------------------------------------------------------------------
# Correlation guard
# ---------------------------------------------------------------------------


def test_correlation_blocks_above_threshold(rm: RiskManager):
    res = rm.check_correlation("A", ["B"], {("A", "B"): 0.85}, threshold=0.7)
    assert res.ok is False
    assert "B" in (res.reason or "")


def test_correlation_handles_reversed_key(rm: RiskManager):
    # Matrix only has (B, A); the guard must still find it.
    res = rm.check_correlation("A", ["B"], {("B", "A"): 0.9})
    assert res.ok is False


def test_correlation_ok_below_threshold(rm: RiskManager):
    res = rm.check_correlation("A", ["B"], {("A", "B"): 0.3})
    assert res.ok is True


def test_correlation_ok_when_unknown(rm: RiskManager):
    # No entry for the pair ⇒ can't block.
    assert rm.check_correlation("A", ["B"], {}).ok is True


# ---------------------------------------------------------------------------
# Van Tharp position sizing
# ---------------------------------------------------------------------------


def test_position_size_rejects_zero_stop(rm: RiskManager):
    with pytest.raises(ValueError):
        rm.position_size_recommend(stop_distance_pct=0.0, portfolio_value_inr=Decimal("100000"))


def test_position_size_respects_notional_cap(rm: RiskManager):
    out = rm.position_size_recommend(
        stop_distance_pct=0.01,  # tight stop ⇒ large raw size
        portfolio_value_inr=Decimal("1000000"),
        risk_per_trade_pct=0.01,
        price_per_unit_inr=Decimal("100"),
    )
    cap = Decimal(out["notional_cap_inr"])
    suggested = Decimal(out["suggested_notional_inr"])
    assert suggested <= cap
    assert cap == Decimal("100000.00")  # 10% of 1M


def test_position_size_risk_amount(rm: RiskManager):
    out = rm.position_size_recommend(
        stop_distance_pct=0.05,
        portfolio_value_inr=Decimal("500000"),
        risk_per_trade_pct=0.01,
    )
    assert Decimal(out["risk_amount_inr"]) == Decimal("5000.00")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_daily_new_positions_remaining(rm: RiskManager):
    assert rm.daily_new_positions_remaining(0) == 2
    assert rm.daily_new_positions_remaining(2) == 0
    assert rm.daily_new_positions_remaining(5) == 0  # never negative


def test_is_today_utc():
    assert RiskManager.is_today_utc(datetime.now(tz=timezone.utc)) is True
    assert RiskManager.is_today_utc(datetime.now(tz=timezone.utc) - timedelta(days=2)) is False
