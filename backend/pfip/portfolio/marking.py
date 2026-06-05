"""Mark-to-market + return-series helpers for the portfolio surface.

Why this module exists
----------------------
``PortfolioService`` already accepts ``mark_prices`` (symbol → current INR per
unit) and ``return_series`` (symbol → daily log-returns) — but nothing fed
them, so ``/portfolio/summary`` showed cost basis and ``/portfolio/correlations``
returned an empty matrix. This wires both from the ``ohlcv`` table.

Correctness-by-abstention
--------------------------
OHLCV ``close`` is denominated in the instrument's *native* currency (INR for
Indian equities, USD for US equities / most crypto pairs). Converting to INR
needs an FX rate. Because ``market`` labels are inconsistent across ingest
sources, :func:`resolve_price_ccy` only returns a currency when it is
*unambiguous*; otherwise it returns ``None`` and the holding is left at cost
basis. A mislabelled market can therefore never produce a wrong rupee figure —
the worst case is an honest "not marked" with a reason the UI can surface.

USD→INR uses the dedicated ``fx_rates`` table (via
:func:`pfip.tax.fx_cost_basis.prefetch_fx_rates`). If no real rate is on hand we
*abstain* rather than fall back to a stale static rate — a live valuation must
not silently use last quarter's FX.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select

from pfip.models.ohlcv import OHLCVRow
from pfip.tax.fx_cost_basis import prefetch_fx_rates

# Markets whose OHLCV close is denominated in INR.
_INR_MARKETS = {"india_equity", "nse", "bse", "in", "india", "inr"}
# Markets whose close is denominated in USD.
_USD_MARKETS = {"us_equity", "us", "nasdaq", "nyse", "usd"}
# Quote tokens we treat as USD-equivalent for FX purposes (stablecoins peg ~1).
_USD_QUOTES = {"USD", "USDT", "USDC", "USDD", "BUSD"}


def resolve_price_ccy(market: str | None, symbol: str | None) -> str | None:
    """Conservatively resolve the currency an OHLCV ``close`` is quoted in.

    Returns ``"INR"``, ``"USD"``, or ``None``. ``None`` means "cannot determine
    confidently" — callers MUST abstain (fall back to cost basis) rather than
    guess, so a mislabelled market never yields a wrong conversion.
    """
    m = (market or "").strip().lower()
    if m in _INR_MARKETS:
        return "INR"
    if m in _USD_MARKETS:
        return "USD"
    # ccxt-style label, e.g. BTC_USD / ETH_USDT / BTC_INR — the quote currency
    # is the trailing token.
    tokens = (market or "").upper().replace("-", "_").replace("/", "_").split("_")
    quote = tokens[-1] if tokens else ""
    if quote == "INR":
        return "INR"
    if quote in _USD_QUOTES:
        return "USD"
    # Bare 'crypto'/unknown market: fall back to the symbol's trailing token.
    stoks = (symbol or "").upper().replace("-", "_").replace("/", "_").split("_")
    ssuf = stoks[-1] if stoks else ""
    if ssuf == "INR":
        return "INR"
    if ssuf in _USD_QUOTES:
        return "USD"
    return None


def compute_log_returns(closes: Iterable[Decimal | float]) -> list[float]:
    """Daily log-returns from an ascending close series. Skips non-positive
    prices (which would make the log undefined) by breaking the pair."""
    vals = [float(c) for c in closes]
    out: list[float] = []
    for prev, cur in zip(vals, vals[1:]):
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


@dataclass(frozen=True)
class MarkResult:
    """Outcome of a mark-to-market pass.

    ``mark_prices`` is the only thing the valuation math consumes; the rest is
    coverage metadata so the UI/user can see what's live-priced vs cost-basis.
    """

    mark_prices: dict[str, Decimal]  # symbol -> current INR per unit (marked only)
    marked: list[str] = field(default_factory=list)
    unmarked: list[dict] = field(default_factory=list)  # [{symbol, reason}]
    usdinr: Decimal | None = None
    as_of: datetime | None = None


def compute_mark_prices(
    latest: dict[str, tuple[Decimal, str | None, datetime | None]],
    symbols: Iterable[str],
    usdinr: Decimal | None,
) -> MarkResult:
    """Pure valuation step. ``latest`` maps symbol → (close, market, ts).

    Pure (no I/O) so the currency/FX logic is unit-testable without a DB.
    """
    mark_prices: dict[str, Decimal] = {}
    marked: list[str] = []
    unmarked: list[dict] = []
    as_of: datetime | None = None

    for sym in symbols:
        row = latest.get(sym)
        if row is None:
            unmarked.append({"symbol": sym, "reason": "no_price"})
            continue
        close, market, ts = row
        if ts is not None and (as_of is None or ts > as_of):
            as_of = ts
        ccy = resolve_price_ccy(market, sym)
        if ccy is None:
            unmarked.append({"symbol": sym, "reason": "unknown_currency"})
            continue
        if ccy == "INR":
            price_inr = Decimal(str(close))
        else:  # USD
            if usdinr is None:
                unmarked.append({"symbol": sym, "reason": "no_fx_rate"})
                continue
            price_inr = (Decimal(str(close)) * usdinr).quantize(Decimal("0.0001"))
        mark_prices[sym] = price_inr
        marked.append(sym)

    return MarkResult(
        mark_prices=mark_prices,
        marked=marked,
        unmarked=unmarked,
        usdinr=usdinr,
        as_of=as_of,
    )


async def fetch_latest_closes(
    db, symbols: Iterable[str]
) -> dict[str, tuple[Decimal, str | None, datetime | None]]:
    """Latest close + market + ts per symbol, in one query (Postgres DISTINCT ON)."""
    syms = [s for s in symbols if s]
    if not syms:
        return {}
    stmt = (
        select(OHLCVRow.symbol, OHLCVRow.close, OHLCVRow.market, OHLCVRow.time)
        .where(OHLCVRow.symbol.in_(syms))
        .order_by(OHLCVRow.symbol, OHLCVRow.time.desc())
        .distinct(OHLCVRow.symbol)
    )
    rows = (await db.execute(stmt)).all()
    return {r.symbol: (Decimal(str(r.close)), r.market, r.time) for r in rows}


async def fetch_return_series(
    db, symbols: Iterable[str], window_days: int
) -> dict[str, list[float]]:
    """Daily log-return series per symbol over the trailing window."""
    syms = [s for s in symbols if s]
    if not syms:
        return {}
    # Buffer a few extra calendar days so we keep ~window_days *returns*.
    since = datetime.now(tz=timezone.utc) - timedelta(days=window_days + 7)
    stmt = (
        select(OHLCVRow.symbol, OHLCVRow.time, OHLCVRow.close)
        .where(OHLCVRow.symbol.in_(syms), OHLCVRow.time >= since)
        .order_by(OHLCVRow.symbol, OHLCVRow.time.asc())
    )
    rows = (await db.execute(stmt)).all()
    by_sym: dict[str, list[Decimal]] = {}
    for r in rows:
        by_sym.setdefault(r.symbol, []).append(Decimal(str(r.close)))
    return {s: compute_log_returns(cl) for s, cl in by_sym.items()}


async def build_marking(db, holdings) -> MarkResult:
    """Fetch latest prices + FX and value the given holdings to INR."""
    symbols = sorted({h.symbol for h in holdings if getattr(h, "symbol", None)})
    if not symbols:
        return MarkResult(mark_prices={})
    latest = await fetch_latest_closes(db, symbols)
    needs_usd = any(
        resolve_price_ccy((latest.get(s) or (None, None, None))[1], s) == "USD"
        for s in symbols
        if s in latest
    )
    usdinr: Decimal | None = None
    if needs_usd:
        cache = await prefetch_fx_rates(db, [("USD", date.today())])
        usdinr = cache.get(("USD", date.today()))
    return compute_mark_prices(latest, symbols, usdinr)


__all__ = [
    "MarkResult",
    "build_marking",
    "compute_log_returns",
    "compute_mark_prices",
    "fetch_latest_closes",
    "fetch_return_series",
    "resolve_price_ccy",
]
