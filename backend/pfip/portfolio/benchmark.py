"""Live portfolio vs benchmark performance.

Compares the portfolio's own value path against a benchmark index
(default NIFTY 50; SENSEX / S&P 500 also supported) over 1M / YTD / 1Y / Max
windows and reports the **excess return** (portfolio minus benchmark) per
window. This is the "am I actually beating the index?" view — the live-book
analogue of the benchmark comparison the backtester already does.

The core (:func:`compare_series`) is pure: it takes two ``(date, value)`` series
and returns the windowed returns + excess, so it is unit-testable without a DB.
:func:`run_benchmark` is the async wrapper that builds the portfolio's
marked-to-market value series and loads the benchmark closes from OHLCV.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)

# Friendly name → the symbol the OHLCV table is likely keyed by. ``run_benchmark``
# tries the alias first, then the raw input, so either form works.
# We benchmark against liquid, investable **tracking ETFs** rather than raw
# index symbols (^NSEI/^GSPC): the index price series aren't reliably available
# from the free sources we use (NSE's index endpoint is flaky; index data on
# AlphaVantage/Polygon free tiers is unavailable), whereas the tracking ETFs
# fetch cleanly via the same daily pipeline. An ETF is also the more honest
# benchmark — it's what the user could actually have bought. See PROXY_NOTES.
BENCHMARK_ALIASES: dict[str, str] = {
    "NIFTY": "NIFTYBEES.NS",
    "NIFTY 50": "NIFTYBEES.NS",
    "NIFTY50": "NIFTYBEES.NS",
    "SENSEX": "^BSESN",  # no reliable free source yet — degrades to a null/no-data note
    "SPX": "SPY",
    "SP500": "SPY",
    "S&P 500": "SPY",
    "SPY": "SPY",
}

# Resolved-symbol → human note shown when an ETF stands in for an index.
PROXY_NOTES: dict[str, str] = {
    "NIFTYBEES.NS": "benchmarked against NIFTYBEES.NS, the NIFTY 50 tracking ETF",
    "SPY": "benchmarked against SPY, the S&P 500 tracking ETF",
}

DEFAULT_BENCHMARK = "NIFTY 50"

# Window label → lookback in days. "YTD" and "Max" are handled specially.
_WINDOW_DAYS: dict[str, int] = {"1M": 30, "3M": 91, "1Y": 365}
_ALL_WINDOWS = ("1M", "3M", "YTD", "1Y", "Max")


def _value_at_or_after(series: list[tuple[date, float]], target: date) -> float | None:
    """First value whose date is >= ``target`` (series sorted ascending)."""
    for d, v in series:
        if d >= target:
            return v
    return None


def _window_start(end: date, window: str) -> date:
    if window == "YTD":
        return date(end.year, 1, 1)
    if window == "Max":
        return date.min
    days = _WINDOW_DAYS.get(window)
    if days is None:
        raise ValueError(f"unknown window {window!r}")
    return end - timedelta(days=days)


def _window_return(series: list[tuple[date, float]], window: str) -> float | None:
    """Cumulative return of ``series`` over ``window`` (None if not enough data)."""
    if len(series) < 2:
        return None
    end_date, end_val = series[-1]
    start_target = _window_start(end_date, window)
    start_val = _value_at_or_after(series, start_target)
    if start_val is None or start_val == 0:
        return None
    return (end_val / start_val) - 1.0


def compare_series(
    portfolio: list[tuple[date, float]],
    benchmark: list[tuple[date, float]],
    *,
    windows: tuple[str, ...] = _ALL_WINDOWS,
) -> dict[str, Any]:
    """Compare two value series over the given windows.

    Each input is a list of ``(date, value)`` sorted ascending. Returns, per
    window, the portfolio return, benchmark return, and excess (portfolio minus
    benchmark) — any of which is ``None`` when that side lacks the history.
    """
    out: dict[str, Any] = {}
    for w in windows:
        pr = _window_return(portfolio, w)
        br = _window_return(benchmark, w)
        excess = (pr - br) if (pr is not None and br is not None) else None
        out[w] = {
            "portfolio_return": None if pr is None else round(pr, 6),
            "benchmark_return": None if br is None else round(br, 6),
            "excess_return": None if excess is None else round(excess, 6),
        }
    return out


# ---------------------------------------------------------------------------
# Async wrapper (DB-backed)
# ---------------------------------------------------------------------------


async def _load_closes(session: Any, symbol: str) -> list[tuple[date, float]]:
    """Load a symbol's daily closes from OHLCV as ``(date, close)`` ascending."""
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
        log.debug("benchmark close load failed for %s: %s", symbol, exc)
        return []
    out: list[tuple[date, float]] = []
    for t, close in rows:
        d = t.date() if hasattr(t, "date") else t
        out.append((d, float(close)))
    return out


async def _load_closes_with_market(
    session: Any, symbol: str
) -> tuple[list[tuple[date, float]], str | None]:
    """Like :func:`_load_closes` but also returns the symbol's OHLCV ``market``
    label, which :func:`resolve_price_ccy` needs to decide INR vs USD."""
    try:
        from sqlalchemy import select

        from pfip.models.ohlcv import OHLCVRow

        stmt = (
            select(OHLCVRow.time, OHLCVRow.close, OHLCVRow.market)
            .where(OHLCVRow.symbol == symbol)
            .order_by(OHLCVRow.time.asc())
        )
        rows = (await session.execute(stmt)).all()
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("benchmark close load failed for %s: %s", symbol, exc)
        return [], None
    out: list[tuple[date, float]] = []
    market: str | None = None
    for t, close, mkt in rows:
        d = t.date() if hasattr(t, "date") else t
        out.append((d, float(close)))
        if market is None:
            market = mkt
    return out, market


async def _portfolio_value_series(session: Any, holdings: list[Any]) -> list[tuple[date, float]]:
    """Build a marked-to-market INR portfolio value series across all holdings.

    For each holding we load its close series (FX-converted to INR per bar date
    for USD-priced names), value qty*close per date, and sum across holdings on
    the unified date axis. Two correctness rules learned the hard way:

    * **Currency** — summing a raw USD close into an INR total understates the
      position ~95×, which silently skews the weights of every window return.
    * **Window start** — the series starts only once EVERY symbol has a price
      (and not before the first acquisition). Starting at the earliest bar of
      *any* symbol made the first "portfolio value" a single cheap position, so
      the "Max" window reported a nonsense +9,646% return.
    """
    import bisect

    from pfip.portfolio.marking import resolve_price_ccy
    from pfip.portfolio.networth import _usd_inr_series

    per_symbol: dict[str, list[tuple[date, float]]] = {}
    market_by: dict[str, str | None] = {}
    qty_by_symbol: dict[str, float] = {}
    first_acquired: date | None = None
    for h in holdings:
        sym = getattr(h, "symbol", None)
        if not sym:
            continue
        qty_by_symbol[sym] = qty_by_symbol.get(sym, 0.0) + float(h.qty)
        acq = getattr(h, "acquired_at", None)
        acq_d = acq.date() if hasattr(acq, "date") else acq
        if acq_d is not None and (first_acquired is None or acq_d < first_acquired):
            first_acquired = acq_d
        if sym not in per_symbol:
            per_symbol[sym], market_by[sym] = await _load_closes_with_market(session, sym)
    per_symbol = {s: v for s, v in per_symbol.items() if v}
    if not per_symbol:
        return []

    # FX-convert USD-priced names to INR at the rate in effect on each bar date.
    usd_syms = [s for s in per_symbol if resolve_price_ccy(market_by.get(s), s) == "USD"]
    if usd_syms:
        fx = await _usd_inr_series(session)
        if not fx:
            # No FX history → abstain from mixing currencies rather than emit
            # a wrong INR figure; drop the USD legs and let the note explain.
            for s in usd_syms:
                per_symbol.pop(s, None)
            if not per_symbol:
                return []
        else:
            fx_dates = [d for d, _ in fx]
            fx_rates = [r for _, r in fx]

            def _rate_on(d: date) -> float:
                i = bisect.bisect_right(fx_dates, d)
                return fx_rates[i - 1] if i > 0 else fx_rates[0]

            for s in usd_syms:
                per_symbol[s] = [(d, px * _rate_on(d)) for d, px in per_symbol[s]]

    # Start where every symbol is priced, and never before the book existed.
    start = max(series[0][0] for series in per_symbol.values())
    if first_acquired is not None and first_acquired > start:
        start = first_acquired
    all_dates = sorted({d for series in per_symbol.values() for d, _ in series if d >= start})
    if not all_dates:
        return []

    # Forward-fill each symbol's price onto the unified date axis.
    series_out: list[tuple[date, float]] = []
    cursors = {s: 0 for s in per_symbol}
    last_price: dict[str, float | None] = {s: None for s in per_symbol}
    for d in all_dates:
        total = 0.0
        for s, closes in per_symbol.items():
            i = cursors[s]
            while i < len(closes) and closes[i][0] <= d:
                last_price[s] = closes[i][1]
                i += 1
            cursors[s] = i
            if last_price[s] is not None:
                total += qty_by_symbol[s] * last_price[s]
        series_out.append((d, total))
    return series_out


async def run_benchmark(
    session: Any,
    *,
    symbol: str = DEFAULT_BENCHMARK,
    windows: tuple[str, ...] = _ALL_WINDOWS,
) -> dict[str, Any]:
    """Compare the live portfolio's value path to a benchmark index."""
    from pfip.portfolio.service import PortfolioService

    resolved = BENCHMARK_ALIASES.get(symbol.upper(), symbol)
    bench = await _load_closes(session, resolved)
    if not bench:
        # Fall back to the raw input symbol before giving up.
        bench = await _load_closes(session, symbol)

    service = PortfolioService(session)
    holdings = await service.list_holdings(active=True)
    portfolio = await _portfolio_value_series(session, holdings)

    # Compare like-for-like: the benchmark side of every window (especially
    # "Max") must cover the same period as the portfolio series, or "Max"
    # compares your ~2-year book against the ETF's full multi-year history.
    if portfolio and bench:
        p_start = portfolio[0][0]
        bench = [(d, v) for d, v in bench if d >= p_start]

    result = compare_series(portfolio, bench, windows=windows)
    note = None
    if not bench:
        note = f"no OHLCV history for benchmark {symbol!r} (tried {resolved!r}) — returns are null"
    elif not portfolio:
        note = "no priced holdings — portfolio returns are null"
    elif resolved in PROXY_NOTES:
        note = PROXY_NOTES[resolved]
    out: dict[str, Any] = {
        "benchmark": symbol,
        "benchmark_symbol_resolved": resolved,
        "windows": result,
        "note": note,
    }
    if portfolio:
        out["series_start"] = portfolio[0][0].isoformat()
        out["series_end"] = portfolio[-1][0].isoformat()
    return out


__all__ = ["compare_series", "run_benchmark", "BENCHMARK_ALIASES", "DEFAULT_BENCHMARK"]
