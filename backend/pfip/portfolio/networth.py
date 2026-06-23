"""Consolidated net-worth timeline across every asset class.

Most portfolio views only mark the *liquid* book (equities/crypto with OHLCV).
Net worth is the whole picture: it also folds in the illiquid / manual holdings
(PPF, EPF, NPS, FD, SGB, G-Sec, bonds, cash, real estate) that have no market
feed. Those are valued at cost basis and held flat from their acquisition date
— honest, if conservative — while priced holdings are marked to their latest
close per day and forward-filled.

The core (:func:`build_networth`) is pure: it takes the holdings plus a
``closes_by_symbol`` map and returns the daily timeline + current breakdown, so
it is unit-testable without a DB. :func:`run_networth` is the async wrapper.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from pfip.core.contracts import HoldingCategory

log = logging.getLogger(__name__)

# Categories that never have an OHLCV feed — valued at cost basis, held flat.
ILLIQUID_CATEGORIES = {
    HoldingCategory.PPF.value,
    HoldingCategory.EPF.value,
    HoldingCategory.NPS.value,
    HoldingCategory.FD.value,
    HoldingCategory.SGB.value,
    HoldingCategory.GSEC.value,
    HoldingCategory.BOND.value,
    HoldingCategory.CASH.value,
}


def _category(h: Any) -> str:
    c = h.category
    return c.value if isinstance(c, HoldingCategory) else str(c)


def build_networth(
    holdings: list[Any],
    closes_by_symbol: dict[str, list[tuple[date, float]]],
) -> dict[str, Any]:
    """Build the net-worth timeline + current breakdown.

    Args:
        holdings: open holdings (need ``category``, ``symbol``, ``qty``,
            ``cost_basis_inr``, ``acquired_at``).
        closes_by_symbol: symbol → ``(date, close)`` ascending, for priced names.

    Returns a dict with ``timeline`` (list of ``{date, net_worth_inr}``),
    ``current_inr``, and ``breakdown_inr`` (category → current value).
    """
    # Per-symbol priced contribution, forward-filled onto the union of dates.
    priced_symbols = {h.symbol for h in holdings if h.symbol and h.symbol in closes_by_symbol}
    qty_by_symbol: dict[str, float] = {}
    for h in holdings:
        if h.symbol in priced_symbols:
            qty_by_symbol[h.symbol] = qty_by_symbol.get(h.symbol, 0.0) + float(h.qty)

    # Flat cost-basis floor from every holding that isn't live-priced.
    flat_value = 0.0
    breakdown: dict[str, float] = {}
    for h in holdings:
        cat = _category(h)
        if h.symbol in priced_symbols:
            continue
        flat_value += float(h.cost_basis_inr)
        breakdown[cat] = breakdown.get(cat, 0.0) + float(h.cost_basis_inr)

    all_dates = sorted({d for s in priced_symbols for d, _ in closes_by_symbol[s]})

    timeline: list[dict[str, Any]] = []
    cursors = {s: 0 for s in priced_symbols}
    last_price: dict[str, float | None] = {s: None for s in priced_symbols}
    for d in all_dates:
        priced_total = 0.0
        for s in priced_symbols:
            closes = closes_by_symbol[s]
            i = cursors[s]
            while i < len(closes) and closes[i][0] <= d:
                last_price[s] = closes[i][1]
                i += 1
            cursors[s] = i
            if last_price[s] is not None:
                priced_total += qty_by_symbol[s] * last_price[s]
        timeline.append({"date": d.isoformat(), "net_worth_inr": round(priced_total + flat_value, 2)})

    # Current priced breakdown (latest close per symbol).
    for h in holdings:
        if h.symbol not in priced_symbols:
            continue
        cat = _category(h)
        last = last_price.get(h.symbol)
        val = (float(h.qty) * last) if last is not None else float(h.cost_basis_inr)
        breakdown[cat] = breakdown.get(cat, 0.0) + val

    current = timeline[-1]["net_worth_inr"] if timeline else round(flat_value, 2)
    return {
        "timeline": timeline,
        "current_inr": current,
        "breakdown_inr": {k: round(v, 2) for k, v in breakdown.items()},
    }


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------


async def _load_closes(session: Any, symbol: str) -> list[tuple[date, float]]:
    try:
        from sqlalchemy import select

        from pfip.models.ohlcv import OHLCVRow

        stmt = (
            select(OHLCVRow.time, OHLCVRow.close)
            .where(OHLCVRow.symbol == symbol)
            .order_by(OHLCVRow.time.asc())
        )
        res = await session.execute(stmt)
        rows = res.all()
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("net-worth close load failed for %s: %s", symbol, exc)
        return []
    return [((t.date() if hasattr(t, "date") else t), float(c)) for t, c in rows]


async def run_networth(session: Any) -> dict[str, Any]:
    """Build the net-worth timeline for the live book."""
    from pfip.portfolio.service import PortfolioService

    holdings = await PortfolioService(session).list_holdings(active=True)
    closes: dict[str, list[tuple[date, float]]] = {}
    for h in holdings:
        if h.symbol and _category(h) not in ILLIQUID_CATEGORIES and h.symbol not in closes:
            series = await _load_closes(session, h.symbol)
            if series:
                closes[h.symbol] = series
    return build_networth(holdings, closes)


__all__ = ["build_networth", "run_networth", "ILLIQUID_CATEGORIES"]
