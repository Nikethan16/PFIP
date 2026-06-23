"""Portfolio stress-testing against named historical shock scenarios.

Applies a set of per-category return shocks — calibrated to real episodes — to
the *current* marked book and reports the projected loss for each. This is a
scenario overlay, not a forecast: "if 2008 happened to today's allocation, how
much would I be down?"

Shocks are expressed per :class:`HoldingCategory` bucket (equity, crypto, gold,
debt, …). The core (:func:`stress_book`) is pure — it takes category values and
returns the per-scenario impact — so it is unit-testable without a DB.
"""

from __future__ import annotations

import logging
from typing import Any

from pfip.core.contracts import HoldingCategory

log = logging.getLogger(__name__)

_EQUITY = HoldingCategory.EQUITY.value
_ETF = HoldingCategory.ETF.value
_MF = HoldingCategory.MUTUAL_FUND.value
_CRYPTO_X = HoldingCategory.CRYPTO_EXCHANGE.value
_CRYPTO_SC = HoldingCategory.CRYPTO_SELF_CUSTODY.value
_SGB = HoldingCategory.SGB.value
_DEBT = HoldingCategory.BOND.value
_GSEC = HoldingCategory.GSEC.value


# Each scenario maps a category → fractional return shock (-0.5 = -50%).
# Categories not listed in a scenario are assumed unaffected (shock 0).
SCENARIOS: dict[str, dict[str, Any]] = {
    "gfc_2008": {
        "label": "2008 Global Financial Crisis",
        "shocks": {_EQUITY: -0.55, _ETF: -0.50, _MF: -0.50, _CRYPTO_X: -0.55,
                   _CRYPTO_SC: -0.55, _SGB: 0.05, _DEBT: -0.05, _GSEC: 0.03},
    },
    "covid_2020": {
        "label": "2020 COVID crash (Feb–Mar)",
        "shocks": {_EQUITY: -0.38, _ETF: -0.34, _MF: -0.34, _CRYPTO_X: -0.50,
                   _CRYPTO_SC: -0.50, _SGB: 0.08, _DEBT: -0.02, _GSEC: 0.02},
    },
    "rate_shock_200bps": {
        "label": "Rate shock +200bps",
        "shocks": {_EQUITY: -0.12, _ETF: -0.12, _MF: -0.12, _CRYPTO_X: -0.15,
                   _CRYPTO_SC: -0.15, _DEBT: -0.08, _GSEC: -0.10, _SGB: -0.03},
    },
    "inr_depreciation_10pct": {
        "label": "INR depreciates 10% vs USD",
        # Rupee-denominated INR equity slightly hit; USD/crypto gain in INR terms.
        "shocks": {_EQUITY: -0.03, _ETF: -0.03, _MF: -0.03, _CRYPTO_X: 0.10,
                   _CRYPTO_SC: 0.10, _SGB: 0.08},
    },
}


def stress_book(values_by_category: dict[str, float]) -> dict[str, Any]:
    """Apply every scenario to a ``category → current INR value`` map.

    Returns total current value plus, per scenario, the shocked value, absolute
    loss, and percentage impact (negative = loss).
    """
    total = sum(values_by_category.values())
    results: list[dict[str, Any]] = []
    for key, spec in SCENARIOS.items():
        shocks = spec["shocks"]
        shocked_total = 0.0
        contributions: dict[str, float] = {}
        for cat, value in values_by_category.items():
            shock = float(shocks.get(cat, 0.0))
            shocked_value = value * (1.0 + shock)
            shocked_total += shocked_value
            if shock != 0.0:
                contributions[cat] = round(value * shock, 2)
        change = shocked_total - total
        results.append(
            {
                "scenario": key,
                "label": spec["label"],
                "shocked_value_inr": round(shocked_total, 2),
                "change_inr": round(change, 2),
                "impact_pct": round((change / total) if total else 0.0, 6),
                "category_pnl_inr": contributions,
            }
        )
    # Worst first.
    results.sort(key=lambda r: r["impact_pct"])
    return {"current_value_inr": round(total, 2), "scenarios": results}


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------


async def run_stress_test(session: Any) -> dict[str, Any]:
    """Run the stress scenarios against the live, marked-to-market book."""
    from decimal import Decimal

    from pfip.portfolio.service import PortfolioService

    service = PortfolioService(session)
    # Mark to latest close where available; exposure_by_category already handles
    # the cost-basis fallback for unpriced names.
    holdings = await service.list_holdings(active=True)
    mark_prices: dict[str, Decimal] = {}
    for h in holdings:
        if not h.symbol:
            continue
        try:
            from sqlalchemy import select

            from pfip.models.ohlcv import OHLCVRow

            stmt = (
                select(OHLCVRow.close)
                .where(OHLCVRow.symbol == h.symbol)
                .order_by(OHLCVRow.time.desc())
                .limit(1)
            )
            res = await session.execute(stmt)
            close = res.scalars().first()
            if close is not None:
                mark_prices[h.symbol] = Decimal(str(close))
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("stress mark load failed for %s: %s", h.symbol, exc)

    exposure = await service.exposure_by_category(mark_prices=mark_prices)
    values = {cat: float(v) for cat, v in exposure.items()}
    return stress_book(values)


__all__ = ["stress_book", "run_stress_test", "SCENARIOS"]
