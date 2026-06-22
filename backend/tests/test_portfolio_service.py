"""Direct unit tests for the financially load-bearing portfolio service.

These exercise the money math in ``pfip.portfolio.service`` directly (rather
than only through the API smoke tests): the pure performance helpers
(``trailing_sharpe`` / ``peak_drawdown``), historical VaR, the Pearson
correlation matrix, holding validation, and the analytics that combine
holdings (exposure / concentration / summary drawdown). To avoid a real DB we
override ``list_holdings`` with a fixed set of ``Holding`` contract objects.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from pfip.core.contracts import Holding, HoldingCategory
from pfip.portfolio.service import (
    HoldingValidationError,
    PortfolioService,
    peak_drawdown,
    trailing_sharpe,
)


def _holding(symbol: str, category: HoldingCategory, qty: str, cost: str, **kw) -> Holding:
    return Holding(
        category=category,
        symbol=symbol,
        acquired_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        qty=Decimal(qty),
        cost_basis_inr=Decimal(cost),
        **kw,
    )


class _FixedHoldingsService(PortfolioService):
    """PortfolioService whose holdings are injected, not read from a DB."""

    def __init__(self, holdings: list[Holding]) -> None:
        super().__init__(db=None)
        self._holdings = holdings

    async def list_holdings(self, *, category=None, active=True):  # noqa: ANN001
        if active is False:
            return [h for h in self._holdings if h.closed_at is not None]
        if active is True:
            return [h for h in self._holdings if h.closed_at is None]
        return list(self._holdings)


# ---------------------------------------------------------------------------
# trailing_sharpe
# ---------------------------------------------------------------------------


def test_trailing_sharpe_too_few_returns_zero():
    assert trailing_sharpe([0.01] * 10, window=30) == 0.0


def test_trailing_sharpe_zero_std_returns_zero():
    # Constant returns ⇒ std 0 ⇒ Sharpe undefined ⇒ 0.0 by contract.
    assert trailing_sharpe([0.01] * 40, window=30) == 0.0


def test_trailing_sharpe_positive_for_steady_gains():
    # Mostly-positive returns with small noise ⇒ positive annualised Sharpe.
    returns = [0.01, 0.012, 0.009, 0.011, 0.013, 0.010] * 6
    s = trailing_sharpe(returns, window=30)
    assert s > 0


def test_trailing_sharpe_uses_only_trailing_window():
    # A wildly negative tail should drag the windowed Sharpe below the
    # all-history one — proving only the last `window` returns are used.
    good = [0.01, 0.011, 0.009] * 12  # 36 points
    full = good + [-0.2, -0.25, -0.3]
    assert trailing_sharpe(full, window=3) < trailing_sharpe(good, window=3)


# ---------------------------------------------------------------------------
# peak_drawdown
# ---------------------------------------------------------------------------


def test_peak_drawdown_empty_is_zero():
    assert peak_drawdown([]) == 0.0


def test_peak_drawdown_monotonic_up_is_zero():
    assert peak_drawdown([100, 110, 120, 130]) == 0.0


def test_peak_drawdown_measures_peak_to_trough():
    # Peak 200 → trough 150 ⇒ 25% drawdown.
    assert peak_drawdown([100, 200, 150, 180]) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# historical_var
# ---------------------------------------------------------------------------


def test_historical_var_requires_30_points():
    svc = PortfolioService(db=None)
    out = svc.historical_var([0.0] * 10)
    assert out["note"] == "n<30"


def test_historical_var_is_negative_tail_and_scales_to_inr():
    svc = PortfolioService(db=None)
    # 100 returns, the worst 10 being -10%; the 95% VaR sits in the left tail.
    returns = [(-0.10 if i < 10 else 0.01) for i in range(100)]
    out = svc.historical_var(
        returns, confidence=0.95, portfolio_value_inr=Decimal("1000000")
    )
    assert out["var_pct"] <= 0
    assert out["cvar_pct"] <= out["var_pct"]  # CVaR is at least as severe
    assert Decimal(out["var_inr"]) > 0  # INR figure is a positive loss magnitude


# ---------------------------------------------------------------------------
# correlation_matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_matrix_empty_without_series():
    svc = PortfolioService(db=None)
    assert await svc.correlation_matrix(None) == {}


@pytest.mark.asyncio
async def test_correlation_matrix_diagonal_is_one():
    svc = PortfolioService(db=None)
    series = {
        "A": [0.01, -0.02, 0.03, -0.01, 0.02, 0.0, 0.015],
        "B": [-0.01, 0.02, -0.03, 0.01, -0.02, 0.0, -0.015],
    }
    m = await svc.correlation_matrix(series, window_days=90)
    assert m["A"]["A"] == pytest.approx(1.0, abs=1e-6)
    # A and B are mirror images ⇒ strongly negatively correlated.
    assert m["A"]["B"] < 0


# ---------------------------------------------------------------------------
# _validate
# ---------------------------------------------------------------------------


def test_validate_rejects_nonpositive_qty():
    with pytest.raises(HoldingValidationError):
        PortfolioService._validate(_holding("X", HoldingCategory.EQUITY, "0", "100"))


def test_validate_requires_fx_for_foreign_ccy():
    h = _holding("AAPL", HoldingCategory.EQUITY, "1", "100", cost_basis_ccy="USD")
    with pytest.raises(HoldingValidationError):
        PortfolioService._validate(h)


def test_validate_self_custody_only_for_crypto():
    h = _holding("X", HoldingCategory.EQUITY, "1", "100", is_self_custody=True)
    with pytest.raises(HoldingValidationError):
        PortfolioService._validate(h)


def test_validate_accepts_clean_holding():
    PortfolioService._validate(_holding("X", HoldingCategory.EQUITY, "1", "100"))


# ---------------------------------------------------------------------------
# exposure / concentration / summary (real logic, injected holdings)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exposure_by_category_uses_mark_prices():
    svc = _FixedHoldingsService(
        [
            _holding("RELIANCE.NS", HoldingCategory.EQUITY, "10", "10000"),
            _holding("BTC/USD", HoldingCategory.CRYPTO_EXCHANGE, "1", "5000000"),
        ]
    )
    # Mark equity up to 1500/unit; leave crypto to fall back to cost basis.
    exposure = await svc.exposure_by_category(mark_prices={"RELIANCE.NS": Decimal("1500")})
    assert exposure["equity"] == Decimal("15000.00")
    assert exposure["crypto_exchange"] == Decimal("5000000")


@pytest.mark.asyncio
async def test_concentration_score_flags_single_position():
    svc = _FixedHoldingsService(
        [_holding("BTC/USD", HoldingCategory.CRYPTO_EXCHANGE, "1", "1000000")]
    )
    out = await svc.concentration_score()
    assert out["hhi"] == pytest.approx(1.0)  # one holding ⇒ fully concentrated
    assert out["n"] == 1


@pytest.mark.asyncio
async def test_concentration_score_lower_when_diversified():
    svc = _FixedHoldingsService(
        [
            _holding("A", HoldingCategory.EQUITY, "1", "1000"),
            _holding("B", HoldingCategory.EQUITY, "1", "1000"),
            _holding("C", HoldingCategory.EQUITY, "1", "1000"),
            _holding("D", HoldingCategory.EQUITY, "1", "1000"),
        ]
    )
    out = await svc.concentration_score()
    assert out["hhi"] == pytest.approx(0.25)  # 4 equal positions ⇒ 1/4


@pytest.mark.asyncio
async def test_portfolio_summary_drawdown_from_nav_history():
    svc = _FixedHoldingsService(
        [_holding("A", HoldingCategory.EQUITY, "10", "1000")]
    )
    nav = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("200")),  # peak
        (date(2024, 1, 3), Decimal("150")),  # 25% below peak
    ]
    summary = await svc.portfolio_summary(
        mark_prices={"A": Decimal("100")}, nav_history=nav
    )
    assert summary.drawdown == pytest.approx(0.25)
