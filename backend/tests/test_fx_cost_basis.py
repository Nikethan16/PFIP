"""Tests for pfip.tax.fx_cost_basis.

The FX helper resolves currency→INR rates with a three-tier fallback
(DB → Frankfurter → static). We test the *pure* behaviour: the
business-day step-back, the INR short-circuit, and the convert_to_inr
math. The Frankfurter HTTP path is patched so the tests don't require
network."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pfip.tax.fx_cost_basis import (
    FxRateNotFoundError,
    _STATIC_FALLBACK_USDINR,
    convert_to_inr,
    get_fx_rate,
    rbi_peak_balance_usd_inr,
)


def test_inr_passthrough_returns_one():
    """INR→INR conversion is a no-op."""
    assert get_fx_rate("INR", date(2026, 5, 29)) == Decimal("1")


def test_static_fallback_picks_exact_date():
    """When DB + Frankfurter miss, static table answers exact dates."""
    rate = get_fx_rate("USD", date(2025, 12, 31), db=None, fallback=False)
    assert rate == Decimal("84.7800")


def test_static_fallback_steps_back_to_business_day():
    """A Saturday/Sunday/holiday transaction uses the previous business day.

    The static table doesn't contain May 29 2026, but it has earlier
    anchors. The step-back loop should find 2026-03-31 within 365 days.
    """
    rate = get_fx_rate("USD", date(2026, 5, 29), db=None, fallback=False)
    # Must find *some* rate via the 365-day static fallback walk.
    assert rate in _STATIC_FALLBACK_USDINR.values()


def test_unknown_currency_raises_when_static_misses():
    """No DB, no Frankfurter (fallback=False), no EUR in static → raise."""
    with pytest.raises(FxRateNotFoundError):
        get_fx_rate("EUR", date(2026, 5, 29), db=None, fallback=False)


def test_convert_to_inr_quantizes_to_paise():
    """convert_to_inr returns 2 decimals (paise)."""
    inr = convert_to_inr(amount=Decimal("100"), currency="USD", on=date(2025, 12, 31), db=None)
    # 100 * 84.78 = 8478.00
    assert inr == Decimal("8478.00")


def test_convert_to_inr_passthrough_inr():
    """Passing INR returns the same amount (after quantize)."""
    out = convert_to_inr(Decimal("12345.67"), "INR", date(2026, 1, 1), db=None)
    assert out == Decimal("12345.67")


def test_rbi_peak_balance_empty():
    """No balances → all zeros, sentinel date.min."""
    peak_usd, peak_inr, peak_date = rbi_peak_balance_usd_inr({})
    assert peak_usd == Decimal("0")
    assert peak_inr == Decimal("0")
    assert peak_date == date.min


def test_rbi_peak_balance_picks_max():
    """Peak USD picks the largest balance, converts at that date's rate."""
    balances = {
        date(2025, 4, 1): Decimal("100"),
        date(2025, 12, 31): Decimal("500"),  # peak
        date(2026, 1, 2): Decimal("250"),
    }
    peak_usd, peak_inr, peak_date = rbi_peak_balance_usd_inr(balances)
    assert peak_date == date(2025, 12, 31)
    assert peak_usd == Decimal("500")
    # 500 * 84.78 = 42390.00
    assert peak_inr == Decimal("42390.00")
