"""Due-diligence aggregation service — the single source of truth.

:func:`build_diligence` assembles a structured, JSON-safe aggregate of
everything PFIP knows about one asset. It is called by both the
``/api/v1/diligence/{symbol}`` REST endpoint and the chat agent's
``get_diligence`` tool, so the aggregation logic lives in exactly one place.

Design rules
------------
- **Degrade gracefully.** Each section is computed in isolation and wrapped so
  that a query failure or absent data yields an empty/null section rather than
  aborting the whole response. The only hard requirement is that the symbol has
  at least one OHLCV bar; without that we return ``found=False`` and the caller
  (endpoint) maps it to a 404.
- **Honest, not fabricated.** The ``summary`` section carries only derived
  annotations with a clear basis (data-coverage note, a neutral valuation
  descriptor when a P/E exists) plus a standing experimental disclaimer. No
  buy/sell calls, no invented analysis.
- **JSON-safe.** Decimals → ``float``/``str``, datetimes/dates → ISO strings,
  so the dict round-trips cleanly through FastAPI *and* the agent formatter.

The data model is an EAV ``fundamentals`` table (``(symbol, field, value,
source, as_of_date)``); we pivot the newest row per ``field`` into a flat dict.
``news`` carries ``category`` (``news`` / ``sec_filing`` / ``corp_announcement``
/ insider disclosures) which we split into filings / insider / general news.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from sqlalchemy import func, select

DISCLAIMER = (
    "Experimental - this is an automated data aggregation for research, "
    "not investment advice. PFIP does not recommend buying or selling any asset."
)

# ---------------------------------------------------------------------------
# Source preference: for a US ticker the same field can exist under several
# sources. finnhub/screener carry clean per-ticker ratios; sec_edgar keys facts
# by ENTITY NAME (not ticker) so it must never win a ticker join. Lower rank =
# preferred when two rows share a (field) for the same newest as_of_date.
# ---------------------------------------------------------------------------
_SOURCE_RANK: dict[str, int] = {
    "finnhub": 0,
    "screener": 0,
    "coingecko": 1,
    "mempool": 1,
    "defillama": 1,
    "fred": 2,
    "world_bank": 2,
    "sec_edgar": 9,  # entity-name keyed — deprioritize for ticker joins
}

# On-chain / crypto fundamentals live under the *base* asset symbol (``BTC``),
# while OHLCV uses the dash pair (``BTC-USD``). These sources are on-chain.
_ONCHAIN_SOURCES = frozenset({"mempool", "coingecko", "defillama"})

# Market-level institutional-flow pseudo-symbols (India FII/DII).
_FLOW_SYMBOLS = ("FII/FPI_FLOW", "DII_FLOW")


# ---------------------------------------------------------------------------
# Small JSON-safe coercion helpers
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float | None:
    """Best-effort numeric → float, else None (never raises)."""
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _iso(value: Any) -> str | None:
    """datetime/date → ISO string, else None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _strip_prefix(field: str) -> str:
    """Drop the ``<source>_`` prefix many fields carry (e.g. ``finnhub_peTTM``)."""
    for pfx in ("finnhub_", "screener_", "mempool_", "sec_edgar_"):
        if field.startswith(pfx):
            return field[len(pfx) :]
    return field


# ---------------------------------------------------------------------------
# Asset-class / market resolution
# ---------------------------------------------------------------------------


def _classify(symbol: str, market: str | None) -> tuple[str, str]:
    """Return ``(market_label, asset_class)`` for a symbol.

    ``market`` (from the OHLCV row) is authoritative when present; otherwise we
    fall back to symbol-shape heuristics so a freshly-added symbol still gets a
    sensible label.
    """
    m = (market or "").upper()
    s = symbol.upper()
    if m.startswith(("BTC", "ETH", "SOL", "BNB")) or "-USD" in s or "-USDT" in s:
        return (market or "crypto", "crypto")
    if m == "US_EQUITY":
        return ("US_EQUITY", "equity")
    if m == "NSE" or s.endswith((".NS", ".BO")):
        return ("NSE", "equity")
    if m == "MF_INDIA":
        return ("MF_INDIA", "mutual_fund")
    if m == "FX":
        return ("FX", "fx")
    if m:
        return (m, "equity")
    return ("unknown", "unknown")


def _crypto_base(symbol: str) -> str:
    """``BTC-USD`` / ``BTC-USDT`` → ``BTC`` (the on-chain fundamentals symbol)."""
    return symbol.upper().split("-", 1)[0].split("/", 1)[0]


# ---------------------------------------------------------------------------
# Section builders — each is defensive and returns a plain dict/list.
# ---------------------------------------------------------------------------


async def _latest_price(session: Any, symbol: str) -> dict[str, Any]:
    """Last daily close + absolute/percent change from the prior daily bar.

    Returns ``{"market": ..., "last_price": ..., "change": ..., "change_pct":
    ..., "as_of": ...}`` with Nones when there are no bars.
    """
    out: dict[str, Any] = {
        "market": None,
        "last_price": None,
        "change": None,
        "change_pct": None,
        "as_of": None,
    }
    try:
        from pfip.models.ohlcv import OHLCVRow

        since = datetime.now(tz=timezone.utc) - timedelta(days=14)
        rows = (
            await session.execute(
                select(OHLCVRow.close, OHLCVRow.time, OHLCVRow.market)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.timeframe == "1d",
                    OHLCVRow.time >= since,
                )
                .order_by(OHLCVRow.time.desc())
                .limit(2)
            )
        ).all()
        if not rows:
            # Widen the window once: a thinly-traded / stale symbol may have its
            # last bar older than 14d. Take the two most-recent bars overall.
            rows = (
                await session.execute(
                    select(OHLCVRow.close, OHLCVRow.time, OHLCVRow.market)
                    .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == "1d")
                    .order_by(OHLCVRow.time.desc())
                    .limit(2)
                )
            ).all()
        if rows:
            last = _to_float(rows[0][0])
            out["last_price"] = last
            out["as_of"] = _iso(rows[0][1])
            out["market"] = rows[0][2]
            if len(rows) > 1:
                prev = _to_float(rows[1][0])
                if last is not None and prev not in (None, 0):
                    out["change"] = round(last - prev, 8)
                    out["change_pct"] = round((last - prev) / prev * 100.0, 4)
    except Exception as exc:  # noqa: BLE001 — price is best-effort
        logger.debug(f"[diligence] last_price failed for {symbol}: {exc}")
    return out


async def _pivot_fundamentals(session: Any, symbol: str) -> dict[str, Any]:
    """Pivot the EAV ``fundamentals`` rows for ``symbol`` into a flat dict.

    Keeps, per ``field``, the value from the newest ``as_of_date``; ties broken
    by source preference (finnhub/screener over sec_edgar). Returns::

        {"as_of_date": ISO|None, "source": str|None, "values": {field: float},
         "raw": {field: {"value", "source", "as_of_date"}}}

    ``values`` strips the ``<source>_`` field prefix for readability; ``raw``
    keeps the original field name + provenance.
    """
    out: dict[str, Any] = {"as_of_date": None, "source": None, "values": {}, "raw": {}}
    try:
        from pfip.models.fundamentals import FundamentalRow

        rows = (
            await session.execute(
                select(
                    FundamentalRow.field,
                    FundamentalRow.value,
                    FundamentalRow.source,
                    FundamentalRow.as_of_date,
                ).where(FundamentalRow.symbol == symbol)
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[diligence] fundamentals query failed for {symbol}: {exc}")
        return out

    # field -> (as_of_date, source_rank, value, source)
    best: dict[str, tuple[Any, int, Any, str]] = {}
    for field, value, source, as_of in rows:
        rank = _SOURCE_RANK.get(source, 5)
        cur = best.get(field)
        cand = (as_of, rank, value, source)
        if cur is None:
            best[field] = cand
            continue
        # Prefer newer as_of_date; on tie prefer the lower source rank.
        if as_of is not None and cur[0] is not None:
            if as_of > cur[0] or (as_of == cur[0] and rank < cur[1]):
                best[field] = cand
        elif as_of is not None and cur[0] is None:
            best[field] = cand

    if not best:
        return out

    newest_date = max((b[0] for b in best.values() if b[0] is not None), default=None)
    # Pick a representative source: the one backing the newest-dated fields.
    src_counts: dict[str, int] = defaultdict(int)
    for _f, (as_of, _r, _v, source) in best.items():
        if as_of == newest_date:
            src_counts[source] += 1
    rep_source = max(src_counts, key=src_counts.get) if src_counts else None

    values: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for field, (as_of, _rank, value, source) in best.items():
        fv = _to_float(value)
        clean = _strip_prefix(field)
        # If two raw fields collapse to the same clean name, keep the first.
        values.setdefault(clean, fv)
        raw[field] = {"value": fv, "source": source, "as_of_date": _iso(as_of)}

    out["as_of_date"] = _iso(newest_date)
    out["source"] = rep_source
    out["values"] = values
    out["raw"] = raw
    return out


def _extract_key_metrics(values: dict[str, Any]) -> dict[str, Any]:
    """Pull a curated, normalized subset of headline ratios from pivoted values.

    Matches the same metric across US (finnhub, already prefix-stripped) and
    India (screener) naming. Only emits a key when a value is actually present,
    so the subset is honest about coverage.
    """
    if not values:
        return {}

    # canonical key -> ordered list of candidate (already prefix-stripped) names.
    # The canonical key itself is appended LAST to each tuple so that on-demand
    # live fundamentals (persisted under canonical field names by the research
    # agent) re-surface here, without changing precedence for existing sources.
    candidates: dict[str, tuple[str, ...]] = {
        "pe_ratio": (
            "peTTM",
            "peAnnual",
            "peNormalizedAnnual",
            "stock_p_e",
            "forwardPE",
            "pe_ratio",
        ),
        "pb_ratio": ("pbAnnual", "pbQuarterly", "ptbvAnnual", "pb_ratio"),
        "price_to_sales": ("psTTM", "psAnnual", "price_to_sales"),
        "gross_margin": ("grossMarginTTM", "grossMarginAnnual", "gross_margin"),
        "operating_margin": ("operatingMarginTTM", "operatingMarginAnnual", "operating_margin"),
        "net_margin": ("netProfitMarginTTM", "netProfitMarginAnnual", "netMarginTTM", "net_margin"),
        "roe": ("roeTTM", "roeRfy", "roe"),
        "roa": ("roaTTM", "roaRfy", "roa"),
        "roce": ("roce", "roiAnnual"),
        "revenue_growth": (
            "revenueGrowthTTMYoy",
            "revenueGrowth3Y",
            "revenueGrowth5Y",
            "revenue_growth",
        ),
        "eps_growth": ("epsGrowthTTMYoy", "epsGrowth3Y", "epsGrowth5Y", "eps_growth"),
        "eps": ("eps",),
        "debt_to_equity": (
            "totalDebt/totalEquityAnnual",
            "longTermDebt/equityAnnual",
            "totalDebt/totalEquityQuarterly",
            "debt_to_equity",
        ),
        "current_ratio": ("currentRatioAnnual", "currentRatioQuarterly", "current_ratio"),
        "market_cap": ("marketCapitalization", "market_cap", "market_cap_usd"),
        "dividend_yield": (
            "currentDividendYieldTTM",
            "dividendYieldIndicatedAnnual",
            "dividend_yield",
        ),
        "beta": ("beta",),
        "book_value": ("bookValuePerShareAnnual", "book_value"),
        "current_price": ("current_price", "price_usd"),
        "52w_high": ("52WeekHigh", "52w_high"),
        "52w_low": ("52WeekLow", "52w_low"),
    }
    out: dict[str, Any] = {}
    for key, names in candidates.items():
        for name in names:
            if name in values and values[name] is not None:
                out[key] = values[name]
                break
    return out


# Category groupings for the three news-derived sections.
_FILING_CATEGORIES = ("sec_filing", "corp_announcement")
_INSIDER_CATEGORIES = ("pit_disclosure", "insider", "insider_trade")
# Categories that are NOT free-text news (excluded from the `news` section so it
# stays editorial; filings/insider get their own sections, earnings_calendar is
# noise here).
_NON_NEWS_CATEGORIES = _FILING_CATEGORIES + _INSIDER_CATEGORIES + ("earnings_calendar",)


async def _news_by_category(session: Any, symbol: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch recent ``news`` rows for ``symbol`` and split them by category.

    Each bucket is queried with its OWN category filter + ordered limit, so a
    symbol with many recent filings can't starve the news section (and vice
    versa). Returns ``{"filings": [...], "insider": [...], "news": [...]}``:

    - ``filings`` — ``sec_filing`` (US) or ``corp_announcement`` (India).
    - ``insider`` — PIT / insider disclosures (empty until that feed lands).
    - ``news`` — editorial news only (regular ``news`` category etc.), excluding
      filings/insider/earnings-calendar rows.
    """
    out: dict[str, list[dict[str, Any]]] = {"filings": [], "insider": [], "news": []}
    try:
        from sqlalchemy import or_

        from pfip.models.news import NewsRow

        # Match the symbol column OR the entity-linked tickers array (news is
        # frequently linked only via entity_tickers, with symbol null). Try both
        # the suffixed and bare forms so RELIANCE.NS and RELIANCE both resolve —
        # an exact symbol== match alone left the sections empty.
        bare = symbol.split(".")[0]
        variants = {symbol, bare}
        symbol_match = or_(
            NewsRow.symbol.in_(list(variants)),
            *[NewsRow.entity_tickers.contains([v]) for v in variants],
        )

        async def _fetch(where_clause, limit: int):
            return (
                (
                    await session.execute(
                        select(NewsRow)
                        .where(symbol_match)
                        .where(where_clause)
                        .order_by(NewsRow.time.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

        filing_rows = await _fetch(NewsRow.category.in_(_FILING_CATEGORIES), 15)
        insider_rows = await _fetch(NewsRow.category.in_(_INSIDER_CATEGORIES), 15)
        news_rows = await _fetch(NewsRow.category.notin_(_NON_NEWS_CATEGORIES), 10)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[diligence] news query failed for {symbol}: {exc}")
        return out

    out["filings"] = [
        {
            "title": r.title,
            "url": r.url,
            "date": _iso(r.time),
            "source": r.source,
            "type": (getattr(r, "category", None) or "filing"),
        }
        for r in filing_rows
    ]
    out["insider"] = [
        {
            "title": r.title,
            "url": r.url,
            "date": _iso(r.time),
            "source": r.source,
            "category": (getattr(r, "category", None) or "insider"),
        }
        for r in insider_rows
    ]
    out["news"] = [
        {
            "title": r.title,
            "sentiment": _to_float(getattr(r, "sentiment", None)),
            "time": _iso(r.time),
            "url": r.url,
            "source": r.source,
        }
        for r in news_rows
    ]
    return out


async def _institutional_flows(session: Any) -> dict[str, Any]:
    """Latest India FII/FPI + DII net/buy/sell flows from ``fundamentals``.

    Market-level (not per ticker). Returns ``{}`` when absent so non-India
    contexts simply omit it.
    """
    try:
        from pfip.models.fundamentals import FundamentalRow

        rows = (
            await session.execute(
                select(
                    FundamentalRow.symbol,
                    FundamentalRow.field,
                    FundamentalRow.value,
                    FundamentalRow.as_of_date,
                )
                .where(FundamentalRow.symbol.in_(_FLOW_SYMBOLS))
                .order_by(FundamentalRow.as_of_date.desc())
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[diligence] institutional flows query failed: {exc}")
        return {}
    if not rows:
        return {}

    newest = rows[0][3]
    flows: dict[str, dict[str, Any]] = {}
    for sym, field, value, as_of in rows:
        if as_of != newest:
            continue
        bucket = "fii" if sym.startswith("FII") else "dii"
        flows.setdefault(bucket, {})[field] = _to_float(value)
    if not flows:
        return {}
    return {"as_of_date": _iso(newest), "unit": "INR crore", **flows}


def _onchain_from_fundamentals(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract on-chain / mempool metrics from the pivoted ``raw`` fundamentals.

    Selects fields whose provenance source is on-chain (mempool / coingecko /
    defillama). Returns ``{}`` for non-crypto assets (they have no such rows).
    """
    out: dict[str, Any] = {}
    for field, meta in (raw or {}).items():
        if isinstance(meta, dict) and meta.get("source") in _ONCHAIN_SOURCES:
            out[_strip_prefix(field)] = meta.get("value")
    return out


async def _model_read(session: Any, symbol: str) -> dict[str, Any]:
    """Latest regime label + latest (experimental) ML signal for ``symbol``."""
    regime: dict[str, Any] | None = None
    signal: dict[str, Any] | None = None
    try:
        from pfip.models.regime import RegimeRow

        r = (
            (
                await session.execute(
                    select(RegimeRow)
                    .where(RegimeRow.symbol == symbol)
                    .order_by(RegimeRow.since.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if r is not None:
            regime = {
                "label": r.regime,
                "confidence": _to_float(r.confidence),
                "since": _iso(r.since),
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[diligence] regime query failed for {symbol}: {exc}")

    try:
        from pfip.models.signals import SignalRow

        s = (
            (
                await session.execute(
                    select(SignalRow)
                    .where(SignalRow.asset == symbol)
                    .order_by(SignalRow.generated_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if s is not None:
            signal = {
                "direction": s.direction,
                "confidence": _to_float(s.confidence),
                "horizon_hours": getattr(s, "horizon_hours", None),
                "model": getattr(s, "model_name", None),
                "generated_at": _iso(s.generated_at),
                "note": "experimental",
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[diligence] signal query failed for {symbol}: {exc}")

    return {
        "regime": regime,
        "signal": signal,
        "disclaimer": "Model read is experimental and not a trade instruction.",
    }


def _build_summary(
    *,
    symbol: str,
    asset_class: str,
    price: dict[str, Any],
    key_metrics: dict[str, Any],
    fundamentals_present: bool,
    n_filings: int,
    n_news: int,
    has_flows: bool,
    has_onchain: bool,
    model_read: dict[str, Any],
) -> dict[str, Any]:
    """Compose honest, derived annotations only — no fabricated analysis.

    Emits a data-coverage line, an optional neutral valuation descriptor *only*
    when a P/E exists (with an explicit, conventional basis), notes on what the
    model currently reads, and the standing experimental disclaimer.
    """
    coverage: list[str] = []
    coverage.append(
        "price history available" if price.get("last_price") is not None else "no price history"
    )
    coverage.append("fundamentals present" if fundamentals_present else "no fundamentals")
    if n_filings:
        coverage.append(f"{n_filings} recent filing(s)")
    if n_news:
        coverage.append(f"{n_news} recent news item(s)")
    if has_flows:
        coverage.append("market FII/DII flows available")
    if has_onchain:
        coverage.append("on-chain metrics available")

    annotations: list[str] = []

    # Neutral valuation descriptor — ONLY with a clear, conventional basis.
    pe = key_metrics.get("pe_ratio")
    if isinstance(pe, (int, float)) and pe > 0:
        # ~16-18x is a long-run broad-market average; describe position vs it
        # without making a call. Bands are descriptive, not predictive.
        if pe < 15:
            band = "below the long-run broad-market average (~16x)"
        elif pe <= 25:
            band = "broadly in line with the long-run broad-market average (~16-25x)"
        else:
            band = "above the long-run broad-market average (~16x)"
        annotations.append(f"P/E {round(pe, 1)} - {band}.")

    dy = key_metrics.get("dividend_yield")
    if isinstance(dy, (int, float)) and dy > 0:
        # finnhub yields are fractional-or-percent depending on field; only state
        # the figure, not a judgement.
        annotations.append(f"Dividend yield reported at {round(dy, 4)} (per source units).")

    # What the model currently reads (descriptive, never a recommendation).
    reg = (model_read or {}).get("regime") or {}
    if reg.get("label"):
        annotations.append(
            f"Current regime read: {reg['label']} " f"(confidence {reg.get('confidence')})."
        )
    sig = (model_read or {}).get("signal") or {}
    if sig.get("direction"):
        annotations.append(
            f"Latest experimental signal: {sig['direction']} "
            f"(confidence {sig.get('confidence')}) - experimental, not advice."
        )

    return {
        "asset_class": asset_class,
        "data_coverage": ", ".join(coverage),
        "annotations": annotations,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def build_diligence(session: Any, symbol: str) -> dict[str, Any]:
    """Aggregate everything known about ``symbol`` into one structured dict.

    Always returns a dict. When the symbol has at least one OHLCV bar the
    ``found`` flag is ``True`` and every section is populated as far as data
    allows (empty/null where there's nothing). When the symbol is entirely
    unknown (no OHLCV at all) ``found`` is ``False`` and the caller should map
    that to a 404; we still return the well-formed skeleton so the agent path
    never crashes.
    """
    symbol = (symbol or "").strip()
    as_of = datetime.now(tz=timezone.utc).isoformat()
    if not symbol:
        return _empty(symbol, as_of, found=False)

    # --- price + asset-class first (also gates found) -----------------------
    price = await _latest_price(session, symbol)
    found = price.get("last_price") is not None
    if not found:
        # No OHLCV bar at all → confirm there is truly nothing for this symbol
        # before declaring it unknown. (Counting avoids a 14-day-window miss.)
        try:
            from pfip.models.ohlcv import OHLCVRow

            n = (
                await session.execute(
                    select(func.count()).select_from(OHLCVRow).where(OHLCVRow.symbol == symbol)
                )
            ).scalar()
            found = bool(n and n > 0)
        except Exception:  # noqa: BLE001
            found = False

    market_label, asset_class = _classify(symbol, price.get("market"))

    # --- fundamentals (ticker) + on-chain (crypto base) ---------------------
    fundamentals = await _pivot_fundamentals(session, symbol)
    # Crypto on-chain/coingecko rows are keyed by the base asset (BTC, not
    # BTC-USD); merge those in so key_metrics + onchain see them.
    if asset_class == "crypto":
        base = _crypto_base(symbol)
        if base and base != symbol:
            base_fund = await _pivot_fundamentals(session, base)
            for clean, val in base_fund.get("values", {}).items():
                fundamentals["values"].setdefault(clean, val)
            fundamentals["raw"].update(base_fund.get("raw", {}))
            if fundamentals.get("as_of_date") is None:
                fundamentals["as_of_date"] = base_fund.get("as_of_date")
                fundamentals["source"] = base_fund.get("source")

    key_metrics = _extract_key_metrics(fundamentals.get("values", {}))
    onchain = _onchain_from_fundamentals(fundamentals.get("raw", {}))

    # --- news / filings / insider ------------------------------------------
    news_split = await _news_by_category(session, symbol)

    # --- institutional flows (India market-level) --------------------------
    flows = await _institutional_flows(session) if asset_class in ("equity", "mutual_fund") else {}

    # --- model read --------------------------------------------------------
    model_read = await _model_read(session, symbol)

    # --- honest summary ----------------------------------------------------
    summary = _build_summary(
        symbol=symbol,
        asset_class=asset_class,
        price=price,
        key_metrics=key_metrics,
        fundamentals_present=bool(fundamentals.get("values")),
        n_filings=len(news_split["filings"]),
        n_news=len(news_split["news"]),
        has_flows=bool(flows),
        has_onchain=bool(onchain),
        model_read=model_read,
    )

    return {
        "symbol": symbol,
        "found": found,
        "as_of": as_of,
        "market": market_label,
        "asset_class": asset_class,
        "last_price": price.get("last_price"),
        "change": price.get("change"),
        "change_pct": price.get("change_pct"),
        "price_as_of": price.get("as_of"),
        "fundamentals": {
            "as_of_date": fundamentals.get("as_of_date"),
            "source": fundamentals.get("source"),
            "key_metrics": key_metrics,
            "values": fundamentals.get("values", {}),
        },
        "filings": news_split["filings"],
        "insider": news_split["insider"],
        "institutional_flows": flows,
        "onchain": onchain,
        "model_read": model_read,
        "news": news_split["news"],
        "summary": summary,
    }


def _empty(symbol: str, as_of: str, *, found: bool) -> dict[str, Any]:
    """Well-formed empty skeleton (used for blank input)."""
    return {
        "symbol": symbol,
        "found": found,
        "as_of": as_of,
        "market": "unknown",
        "asset_class": "unknown",
        "last_price": None,
        "change": None,
        "change_pct": None,
        "price_as_of": None,
        "fundamentals": {"as_of_date": None, "source": None, "key_metrics": {}, "values": {}},
        "filings": [],
        "insider": [],
        "institutional_flows": {},
        "onchain": {},
        "model_read": {"regime": None, "signal": None},
        "news": [],
        "summary": {
            "asset_class": "unknown",
            "data_coverage": "no data",
            "annotations": [],
            "disclaimer": DISCLAIMER,
        },
    }


__all__ = ["build_diligence", "DISCLAIMER"]
