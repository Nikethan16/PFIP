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


async def _portfolio_value_series(session: Any, holdings: list[Any]) -> list[tuple[date, float]]:
    """Build a marked-to-market portfolio value series across all holdings.

    For each holding we load its close series and value qty*close per date, then
    sum across holdings on the union of dates (forward-filling each holding's
    last known price). This is a market-value path — it ignores intra-window
    cash flows, which is acceptable for a relative-vs-benchmark read.
    """
    per_symbol: dict[str, list[tuple[date, float]]] = {}
    qty_by_symbol: dict[str, float] = {}
    for h in holdings:
        sym = getattr(h, "symbol", None)
        if not sym:
            continue
        qty_by_symbol[sym] = qty_by_symbol.get(sym, 0.0) + float(h.qty)
        if sym not in per_symbol:
            per_symbol[sym] = await _load_closes(session, sym)

    all_dates = sorted({d for series in per_symbol.values() for d, _ in series})
    if not all_dates:
        return []

    # Forward-fill each symbol's price onto the unified date axis.
    series_out: list[tuple[date, float]] = []
    cursors = {s: 0 for s in per_symbol}
    last_price = {s: None for s in per_symbol}
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

    result = compare_series(portfolio, bench, windows=windows)
    note = None
    if not bench:
        note = f"no OHLCV history for benchmark {symbol!r} (tried {resolved!r}) — returns are null"
    elif not portfolio:
        note = "no priced holdings — portfolio returns are null"
    elif resolved in PROXY_NOTES:
        note = PROXY_NOTES[resolved]
    return {
        "benchmark": symbol,
        "benchmark_symbol_resolved": resolved,
        "windows": result,
        "note": note,
    }


__all__ = ["compare_series", "run_benchmark", "BENCHMARK_ALIASES", "DEFAULT_BENCHMARK"]
