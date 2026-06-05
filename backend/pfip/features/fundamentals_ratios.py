"""Fundamentals ratios: P/E, P/B, debt/equity, current ratio, ROE, ROIC, etc.

Pure-function helpers; no DB. The fundamentals table is normalized to
GAAP-ish line items (revenue, net_income, total_equity, total_debt,
shares_outstanding, etc.) and these helpers compute the common ratios
on demand. Caller decides what to persist.

Guard rails:
- Every helper returns None when an input is missing/zero/negative-where-meaningless
  rather than propagating NaN.
- All inputs and outputs are float; no Decimal arithmetic (these are
  derived numbers used for ranking, not for tax).

The list deliberately stops at "what an investor checks before buying
a stock". Bigger frameworks (DuPont, Piotroski, Beneish) layer on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(slots=True)
class Fundamentals:
    """Minimal row needed by the ratio helpers."""

    price: float | None = None
    eps_ttm: float | None = None  # earnings per share, trailing twelve months
    book_value_per_share: float | None = None
    total_debt: float | None = None
    total_equity: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    net_income: float | None = None
    revenue: float | None = None
    free_cash_flow: float | None = None
    dividend_per_share: float | None = None
    invested_capital: float | None = None


def _pos(x: float | None) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def pe_ratio(f: Fundamentals) -> float | None:
    """Price / EPS-TTM. Only meaningful when EPS > 0."""
    if f.price is None or _pos(f.eps_ttm) is None:
        return None
    return float(f.price) / float(f.eps_ttm)  # type: ignore[arg-type]


def pb_ratio(f: Fundamentals) -> float | None:
    """Price / Book-value-per-share. Book may be negative; we return None."""
    if f.price is None or _pos(f.book_value_per_share) is None:
        return None
    return float(f.price) / float(f.book_value_per_share)  # type: ignore[arg-type]


def debt_to_equity(f: Fundamentals) -> float | None:
    """Total debt / total equity. Equity > 0 required."""
    if f.total_debt is None or _pos(f.total_equity) is None:
        return None
    return float(f.total_debt) / float(f.total_equity)  # type: ignore[arg-type]


def current_ratio(f: Fundamentals) -> float | None:
    """Current assets / current liabilities. Liabilities > 0 required."""
    if f.current_assets is None or _pos(f.current_liabilities) is None:
        return None
    return float(f.current_assets) / float(f.current_liabilities)  # type: ignore[arg-type]


def return_on_equity(f: Fundamentals) -> float | None:
    """Net income / total equity."""
    if f.net_income is None or _pos(f.total_equity) is None:
        return None
    return float(f.net_income) / float(f.total_equity)  # type: ignore[arg-type]


def return_on_invested_capital(f: Fundamentals) -> float | None:
    """Net income / invested capital. Cheap approximation; ignores tax shield."""
    if f.net_income is None or _pos(f.invested_capital) is None:
        return None
    return float(f.net_income) / float(f.invested_capital)  # type: ignore[arg-type]


def fcf_yield(f: Fundamentals) -> float | None:
    """FCF / market cap (approximated as price × shares; here we use price only
    because shares aren't in the minimal struct — caller multiplies if needed)."""
    if f.free_cash_flow is None or _pos(f.price) is None:
        return None
    # Returns FCF per unit price (use cautiously).
    return float(f.free_cash_flow) / float(f.price)  # type: ignore[arg-type]


def dividend_yield(f: Fundamentals) -> float | None:
    """Annual DPS / price."""
    if f.dividend_per_share is None or _pos(f.price) is None:
        return None
    return float(f.dividend_per_share) / float(f.price)  # type: ignore[arg-type]


def compute_all(f: Fundamentals) -> dict[str, float | None]:
    """Return a flat dict of every ratio; None where inputs missing."""
    return {
        "pe_ratio": pe_ratio(f),
        "pb_ratio": pb_ratio(f),
        "debt_to_equity": debt_to_equity(f),
        "current_ratio": current_ratio(f),
        "return_on_equity": return_on_equity(f),
        "return_on_invested_capital": return_on_invested_capital(f),
        "fcf_yield": fcf_yield(f),
        "dividend_yield": dividend_yield(f),
    }


def fundamentals_from_dict(d: Mapping[str, float | None]) -> Fundamentals:
    """Build a Fundamentals from a tolerant dict (e.g. straight from DB row)."""
    return Fundamentals(
        price=d.get("price"),
        eps_ttm=d.get("eps_ttm"),
        book_value_per_share=d.get("book_value_per_share"),
        total_debt=d.get("total_debt"),
        total_equity=d.get("total_equity"),
        current_assets=d.get("current_assets"),
        current_liabilities=d.get("current_liabilities"),
        net_income=d.get("net_income"),
        revenue=d.get("revenue"),
        free_cash_flow=d.get("free_cash_flow"),
        dividend_per_share=d.get("dividend_per_share"),
        invested_capital=d.get("invested_capital"),
    )


__all__ = [
    "Fundamentals",
    "compute_all",
    "current_ratio",
    "debt_to_equity",
    "dividend_yield",
    "fcf_yield",
    "fundamentals_from_dict",
    "pb_ratio",
    "pe_ratio",
    "return_on_equity",
    "return_on_invested_capital",
]
