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

import bisect
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


def _acq_date(h: Any) -> date | None:
    """Acquisition date of a holding, or None when unknown."""
    a = getattr(h, "acquired_at", None)
    if a is None:
        return None
    return a.date() if hasattr(a, "date") else a


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
    priced_symbols = {h.symbol for h in holdings if h.symbol and h.symbol in closes_by_symbol}

    # Each lot carries its acquisition date so it only contributes to the
    # timeline from the day it was actually held — otherwise a position opened
    # last year would inflate net worth across the full price history behind it.
    priced_lots = [
        (h.symbol, float(h.qty), _acq_date(h)) for h in holdings if h.symbol in priced_symbols
    ]
    flat_lots = [
        (float(h.cost_basis_inr), _acq_date(h)) for h in holdings if h.symbol not in priced_symbols
    ]
    flat_total = sum(cb for cb, _ in flat_lots)

    all_dates = sorted({d for s in priced_symbols for d, _ in closes_by_symbol[s]})

    # Start the timeline at the first acquisition, not at the oldest OHLCV bar
    # of any symbol — otherwise years of pre-ownership dates render as a flat
    # zero line (and a ~130 KB payload of `net_worth_inr: 0` rows).
    known_acq = [a for _, _, a in priced_lots if a is not None] + [
        a for _, a in flat_lots if a is not None
    ]
    if known_acq:
        first_acq = min(known_acq)
        all_dates = [d for d in all_dates if d >= first_acq]

    timeline: list[dict[str, Any]] = []
    cursors = {s: 0 for s in priced_symbols}
    last_price: dict[str, float | None] = {s: None for s in priced_symbols}
    for d in all_dates:
        for s in priced_symbols:
            closes = closes_by_symbol[s]
            i = cursors[s]
            while i < len(closes) and closes[i][0] <= d:
                last_price[s] = closes[i][1]
                i += 1
            cursors[s] = i
        # A lot counts only once its acquisition date has passed (acq None ⇒ unknown,
        # treated as always-held so we never under-report).
        priced_total = sum(
            qty * last_price[sym]
            for sym, qty, acq in priced_lots
            if (acq is None or acq <= d) and last_price[sym] is not None
        )
        flat_at_d = sum(cb for cb, acq in flat_lots if acq is None or acq <= d)
        timeline.append(
            {"date": d.isoformat(), "net_worth_inr": round(priced_total + flat_at_d, 2)}
        )

    # Current breakdown: priced names at their latest close, everything else at cost.
    breakdown: dict[str, float] = {}
    for h in holdings:
        cat = _category(h)
        if h.symbol in priced_symbols:
            last = last_price.get(h.symbol)
            val = (float(h.qty) * last) if last is not None else float(h.cost_basis_inr)
        else:
            val = float(h.cost_basis_inr)
        breakdown[cat] = breakdown.get(cat, 0.0) + val

    current = timeline[-1]["net_worth_inr"] if timeline else round(flat_total, 2)

    # Keep the payload chart-sized: beyond ~500 points, stride-sample the
    # middle but always keep the first and the final point (the current value).
    if len(timeline) > 500:
        stride = max(len(timeline) // 400, 1)
        sampled = timeline[::stride]
        if sampled[-1] is not timeline[-1]:
            sampled.append(timeline[-1])
        timeline = sampled

    return {
        "timeline": timeline,
        "current_inr": current,
        "breakdown_inr": {k: round(v, 2) for k, v in breakdown.items()},
    }


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------


async def _load_closes_batch(
    session: Any, symbols: list[str]
) -> dict[str, list[tuple[date, float]]]:
    """Load full daily close history for several symbols in a single query."""
    if not symbols:
        return {}
    try:
        from sqlalchemy import select

        from pfip.models.ohlcv import OHLCVRow

        stmt = (
            select(OHLCVRow.symbol, OHLCVRow.time, OHLCVRow.close, OHLCVRow.market)
            .where(OHLCVRow.symbol.in_(symbols))
            .order_by(OHLCVRow.symbol.asc(), OHLCVRow.time.asc())
        )
        res = await session.execute(stmt)
        rows = res.all()
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("net-worth batch close load failed: %s", exc)
        return {}
    out: dict[str, list[tuple[date, float]]] = {}
    market_by: dict[str, str | None] = {}
    for sym, t, c, market in rows:
        out.setdefault(sym, []).append(((t.date() if hasattr(t, "date") else t), float(c)))
        market_by.setdefault(sym, market)

    # OHLCV ``close`` is in the instrument's native currency. USD-priced names
    # (US equities, most crypto) must be converted to INR or net worth is wildly
    # understated. Convert each close with the USD->INR rate in effect *on that
    # bar's date* (as-of lookup), so the historical timeline isn't skewed by
    # today's FX; INR names pass through unchanged.
    try:
        from pfip.portfolio.marking import resolve_price_ccy

        usd_syms = [s for s in out if resolve_price_ccy(market_by.get(s), s) == "USD"]
        if usd_syms:
            fx = await _usd_inr_series(session)
            if fx:
                fx_dates = [d for d, _ in fx]
                fx_rates = [r for _, r in fx]

                def _rate_on(d: date) -> float:
                    # Latest rate at-or-before ``d``; earliest rate for dates
                    # that predate any FX history (closest available).
                    i = bisect.bisect_right(fx_dates, d)
                    return fx_rates[i - 1] if i > 0 else fx_rates[0]

                for s in usd_syms:
                    out[s] = [(d, px * _rate_on(d)) for d, px in out[s]]
    except Exception as exc:  # pragma: no cover - defensive; never break the timeline
        log.debug("net-worth FX conversion skipped: %s", exc)
    return out


async def _usd_inr_series(session: Any) -> list[tuple[date, float]]:
    """Full USD->INR history as ascending ``(date, rate)`` for as-of conversion.

    One query (vs. per-date round-trips); the caller bisects it to value each
    historical close at the rate that was actually in effect on its bar date.
    """
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(
                "SELECT rate_date, rate FROM fx_rates "
                "WHERE base = 'USD' AND quote = 'INR' ORDER BY rate_date ASC"
            )
        )
    ).all()
    series: list[tuple[date, float]] = []
    for rd, rate in rows:
        d = rd.date() if hasattr(rd, "date") else rd
        series.append((d, float(rate)))
    return series


async def run_networth(session: Any) -> dict[str, Any]:
    """Build the net-worth timeline for the live book."""
    from pfip.portfolio.service import PortfolioService

    holdings = await PortfolioService(session).list_holdings(active=True)
    symbols = sorted(
        {h.symbol for h in holdings if h.symbol and _category(h) not in ILLIQUID_CATEGORIES}
    )
    closes = {s: v for s, v in (await _load_closes_batch(session, symbols)).items() if v}
    return build_networth(holdings, closes)


__all__ = ["build_networth", "run_networth", "ILLIQUID_CATEGORIES"]
