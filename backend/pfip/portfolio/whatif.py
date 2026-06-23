"""What-if pre-trade simulator.

Answers: *"If I BUY/SELL this, what happens to my book?"* — before/after
exposure-by-category, concentration (HHI), and, for a SELL, the Indian
capital-gains tax it would realise. Advisory only; never executes anything.

The core (:func:`simulate`) is pure: it takes the current holdings list and a
proposed trade and returns the deltas, so it is testable without a DB. The
async :func:`run_what_if` wrapper just fetches the live holdings first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pfip.core.contracts import Holding, HoldingCategory
from pfip.tax.engine import (
    compute_ltcg,
    compute_stcg,
    compute_vda_tax,
    classify_capital_gains,
)
from pfip.tax.indian_rules import DISCLAIMER, is_vda


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _unit_price(h: Holding, mark_prices: dict[str, Decimal] | None) -> Decimal:
    """Per-unit value: live mark when available, else cost basis per unit."""
    if mark_prices and h.symbol and h.symbol in mark_prices:
        return Decimal(str(mark_prices[h.symbol]))
    qty = Decimal(str(h.qty))
    return (Decimal(str(h.cost_basis_inr)) / qty) if qty > 0 else Decimal("0")


def _value(h: Holding, mark_prices: dict[str, Decimal] | None) -> Decimal:
    return (_unit_price(h, mark_prices) * Decimal(str(h.qty))).quantize(Decimal("0.01"))


def _exposure(holdings: list[Holding], mark_prices: dict[str, Decimal] | None) -> dict[str, float]:
    out: dict[str, Decimal] = {}
    for h in holdings:
        cat = h.category.value if isinstance(h.category, HoldingCategory) else str(h.category)
        out[cat] = out.get(cat, Decimal("0")) + _value(h, mark_prices)
    return {k: float(v) for k, v in out.items()}


def _hhi(holdings: list[Holding], mark_prices: dict[str, Decimal] | None) -> float:
    values: dict[str, Decimal] = {}
    for h in holdings:
        key = h.symbol or (h.category.value if isinstance(h.category, HoldingCategory) else "?")
        values[key] = values.get(key, Decimal("0")) + _value(h, mark_prices)
    total = sum(values.values(), Decimal("0"))
    if total <= 0:
        return 0.0
    return float(sum((v / total) ** 2 for v in values.values()))


def _guess_category(symbol: str) -> HoldingCategory:
    s = symbol.upper()
    if "/" in s or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC"):
        return HoldingCategory.CRYPTO_EXCHANGE
    return HoldingCategory.EQUITY


@dataclass(frozen=True)
class _SellInfo:
    """What was realised by a simulated SELL — captured before mutation."""

    symbol: str
    sold_qty: Decimal
    unit_cost_inr: Decimal
    acquired_at: datetime


def _apply_trade(
    holdings: list[Holding],
    *,
    action: str,
    symbol: str,
    qty: Decimal,
    price: Decimal,
) -> tuple[list[Holding], _SellInfo | None]:
    """Return (new_holdings, sell_info).

    BUY: increase an existing position in ``symbol`` or append a new one.
    SELL: reduce the matching position (clamped to what's held); a ``_SellInfo``
    snapshot (taken before the cost basis is reduced) is returned so the caller
    can compute the realised tax even on a full close.
    """
    action = action.upper()
    new: list[Holding] = [h.model_copy(deep=True) for h in holdings]
    notional = (qty * price).quantize(Decimal("0.01"))

    if action == "BUY":
        for h in new:
            if h.symbol == symbol and h.closed_at is None:
                h.qty = Decimal(str(h.qty)) + qty
                h.cost_basis_inr = Decimal(str(h.cost_basis_inr)) + notional
                return new, None
        new.append(
            Holding(
                category=_guess_category(symbol),
                symbol=symbol,
                acquired_at=datetime.now(tz=timezone.utc),
                qty=qty,
                cost_basis_inr=notional,
            )
        )
        return new, None

    if action == "SELL":
        for h in new:
            if h.symbol == symbol and h.closed_at is None:
                held = Decimal(str(h.qty))
                if held <= 0:
                    continue
                sold = min(held, qty)
                unit_cost = (Decimal(str(h.cost_basis_inr)) / held).quantize(Decimal("0.0001"))
                info = _SellInfo(
                    symbol=symbol,
                    sold_qty=sold,
                    unit_cost_inr=unit_cost,
                    acquired_at=h.acquired_at,
                )
                # Reduce cost basis proportionally to qty sold.
                h.cost_basis_inr = (
                    Decimal(str(h.cost_basis_inr)) * (held - sold) / held
                ).quantize(Decimal("0.01"))
                h.qty = held - sold
                if h.qty <= 0:
                    new = [x for x in new if x is not h]
                return new, info
        # Nothing to sell.
        return new, None

    raise ValueError(f"action must be BUY or SELL, got {action!r}")


def _tax_on_sell(info: _SellInfo, *, price: Decimal) -> dict[str, Any]:
    """Estimate the Indian capital-gains tax of a simulated SELL.

    Synthesises a BUY (at the position's per-unit cost / acquisition date) and a
    SELL (now, at ``price``) and runs them through the real FIFO classifier + the
    STCG/LTCG/VDA computations, so this matches the tax engine exactly.
    """
    if info.sold_qty <= 0 or not info.symbol:
        return {"tax_inr": 0.0, "note": "nothing realised"}

    tx_list = [
        {
            "symbol": info.symbol,
            "time": info.acquired_at,
            "kind": "BUY",
            "qty": info.sold_qty,
            "price": info.unit_cost_inr,
        },
        {
            "symbol": info.symbol,
            "time": datetime.now(tz=timezone.utc),
            "kind": "SELL",
            "qty": info.sold_qty,
            "price": price,
        },
    ]
    events = classify_capital_gains(tx_list)
    gain = sum((e.gain_inr for e in events), Decimal("0"))
    if is_vda(info.symbol):
        vda = compute_vda_tax(events)
        tax = Decimal(str(vda.get("tax_inr", vda.get("tax", 0))))
        return {
            "tax_inr": float(tax),
            "asset_class": "vda",
            "realised_gain_inr": float(gain),
            "detail": {
                k: float(v) if isinstance(v, (int, float, Decimal)) else v
                for k, v in vda.items()
            },
        }
    stcg = compute_stcg(events)
    ltcg = compute_ltcg(events)
    return {
        "tax_inr": float(stcg + ltcg),
        "asset_class": "equity",
        "stcg_tax_inr": float(stcg),
        "ltcg_tax_inr": float(ltcg),
        "realised_gain_inr": float(gain),
    }


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WhatIfResult:
    action: str
    symbol: str
    qty: float
    price: float
    before: dict[str, Any]
    after: dict[str, Any]
    deltas: dict[str, Any]
    tax_impact: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "qty": self.qty,
            "price": self.price,
            "before": self.before,
            "after": self.after,
            "deltas": self.deltas,
            "tax_impact": self.tax_impact,
            "disclaimer": DISCLAIMER,
        }


def _snapshot(holdings: list[Holding], mark_prices: dict[str, Decimal] | None) -> dict[str, Any]:
    total = sum((_value(h, mark_prices) for h in holdings), Decimal("0"))
    return {
        "total_value_inr": float(total),
        "n_positions": len([h for h in holdings if Decimal(str(h.qty)) > 0]),
        "exposure_by_category_inr": _exposure(holdings, mark_prices),
        "hhi": _hhi(holdings, mark_prices),
    }


def simulate(
    holdings: list[Holding],
    *,
    action: str,
    symbol: str,
    qty: Decimal | float | str,
    price: Decimal | float | str,
    mark_prices: dict[str, Decimal] | None = None,
) -> WhatIfResult:
    """Pure core: simulate a proposed trade against the given holdings."""
    qd = Decimal(str(qty))
    pd_ = Decimal(str(price))
    if qd <= 0:
        raise ValueError("qty must be > 0")

    before = _snapshot(holdings, mark_prices)
    after_holdings, sell_info = _apply_trade(
        holdings, action=action, symbol=symbol, qty=qd, price=pd_
    )
    after = _snapshot(after_holdings, mark_prices)

    tax_impact: dict[str, Any] = {"tax_inr": 0.0}
    if action.upper() == "SELL" and sell_info is not None:
        tax_impact = _tax_on_sell(sell_info, price=pd_)

    deltas = {
        "total_value_inr": round(after["total_value_inr"] - before["total_value_inr"], 2),
        "hhi": round(after["hhi"] - before["hhi"], 6),
        "n_positions": after["n_positions"] - before["n_positions"],
    }
    return WhatIfResult(
        action=action.upper(),
        symbol=symbol,
        qty=float(qd),
        price=float(pd_),
        before=before,
        after=after,
        deltas=deltas,
        tax_impact=tax_impact,
    )


async def run_what_if(
    service: Any,
    *,
    action: str,
    symbol: str,
    qty: Decimal | float | str,
    price: Decimal | float | str,
    mark_prices: dict[str, Decimal] | None = None,
) -> WhatIfResult:
    """Fetch live holdings via ``service`` then run the pure :func:`simulate`."""
    holdings = await service.list_holdings(active=True)
    return simulate(
        holdings,
        action=action,
        symbol=symbol,
        qty=qty,
        price=price,
        mark_prices=mark_prices,
    )


__all__ = ["WhatIfResult", "simulate", "run_what_if"]
