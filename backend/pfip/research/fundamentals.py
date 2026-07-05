"""On-demand live fundamentals for *untracked* companies (Phase 6+).

When Deep Research is asked about a company that is NOT in PFIP's tracked
universe, ``build_diligence`` has nothing to pivot — the dossier would be a thin
"add it to your watchlist" stub. This module fetches a company's headline
fundamentals **live**, on the spot, so the *first* search returns real revenue
growth, margins, debt, valuation and a business overview.

Tiering (reliability first):

1. **Alpha Vantage ``OVERVIEW``** — keyed, stable from a datacenter IP, and the
   one source we know is reachable from the VM (Yahoo rate-limits the VM IP).
   Covers US tickers natively and Indian listings via the ``.BSE`` suffix.
2. **yfinance ``.info``** — best-effort fallback (works locally / for NSE names;
   may be rate-limited on the VM, so it degrades silently).

Output is normalised to the **same** ``key_metrics`` keys that
``diligence.service._extract_key_metrics`` emits, so the dossier prompt and the
UI treat tracked and on-demand fundamentals identically.

No key set / nothing reachable → returns ``{}``; the caller falls back to the
honest "add to watchlist" framing. This never raises.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from pfip.core.logging import get_logger
from pfip.ingest._common.http import get_async_client, retry_http

log = get_logger("pfip.research.fundamentals")

_AV_BASE = "https://www.alphavantage.co/query"


def alphavantage_key() -> str:
    """Alpha Vantage key, tolerating both env-var spellings.

    The canonical name is ``ALPHAVANTAGE_API_KEY``, but ``ALPHA_VANTAGE_API_KEY``
    (with the underscore) is an easy mistake to make in a hand-edited ``.env``;
    accept either so a misspelled key never silently disables the source.
    """
    return (
        os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY") or ""
    ).strip()


# Alpha Vantage OVERVIEW field -> our canonical key_metrics name.
_AV_METRIC_MAP: dict[str, str] = {
    "PERatio": "pe_ratio",
    "PriceToBookRatio": "pb_ratio",
    "PriceToSalesRatioTTM": "price_to_sales",
    "OperatingMarginTTM": "operating_margin",
    "ProfitMargin": "net_margin",
    "ReturnOnEquityTTM": "roe",
    "ReturnOnAssetsTTM": "roa",
    "QuarterlyRevenueGrowthYOY": "revenue_growth",
    "QuarterlyEarningsGrowthYOY": "eps_growth",
    "MarketCapitalization": "market_cap",
    "DividendYield": "dividend_yield",
    "Beta": "beta",
    "BookValue": "book_value",
    "EPS": "eps",
    "52WeekHigh": "52w_high",
    "52WeekLow": "52w_low",
}


def _f(v: Any) -> float | None:
    """Best-effort float; AV uses the string ``"None"`` for missing values."""
    if v is None or v == "None" or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Canonical metrics the app expresses as PERCENT (finnhub + screener emit
# percent natively); sources that report fractions get ×100 on the way in.
_FRACTION_TO_PCT = {
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "revenue_growth",
    "eps_growth",
    "dividend_yield",
}


def _av_candidates(symbols: list[str], resolved: dict[str, Any]) -> list[str]:
    """Map our DB-style symbols to Alpha Vantage tickers.

    AV wants the BARE US ticker, and uses the ``.BSE`` suffix for Indian names
    (not ``.NS``/``.BO``). De-dupes while preserving order.
    """
    out: list[str] = []
    for s in symbols:
        base = s.split(".")[0].upper()
        if s.upper().endswith((".NS", ".BO")):
            out += [f"{base}.BSE", base]
        else:
            out += [base]
    seen: set[str] = set()
    uniq: list[str] = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


@retry_http(max_attempts=2)
async def _av_get(params: dict[str, str]) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(_AV_BASE, params=params)
        r.raise_for_status()
        return r.json()


async def _alphavantage_overview(symbols: list[str], resolved: dict[str, Any]) -> dict[str, Any]:
    """Fetch OVERVIEW for the first AV-candidate that returns a real company."""
    key = alphavantage_key()
    if not key:
        return {}
    for av_sym in _av_candidates(symbols, resolved):
        try:
            data = await _av_get({"function": "OVERVIEW", "symbol": av_sym, "apikey": key})
        except Exception as e:  # noqa: BLE001
            log.warning(f"AV OVERVIEW {av_sym} failed: {type(e).__name__}: {e}")
            continue
        # Rate-limit / empty responses come back as {"Note": ...} / {"Information": ...} / {}.
        if not data or "Symbol" not in data:
            if data.get("Note") or data.get("Information"):
                log.warning("AV OVERVIEW rate-limited; stopping")
                break
            continue
        metrics: dict[str, Any] = {}
        for av_field, canon in _AV_METRIC_MAP.items():
            val = _f(data.get(av_field))
            if val is not None:
                # AV reports margins/returns/growth/yield as FRACTIONS (0.2431)
                # — normalise to percent, the app-wide convention (finnhub and
                # screener both emit percent for these fields).
                if canon in _FRACTION_TO_PCT:
                    val = round(val * 100.0, 4)
                metrics[canon] = val
        return {
            "source": "alphavantage",
            "matched_symbol": av_sym,
            "name": data.get("Name"),
            "description": data.get("Description"),
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),
            "exchange": data.get("Exchange"),
            "currency": data.get("Currency"),
            "key_metrics": metrics,
        }
    return {}


# Screener.in top-ratio card key -> our canonical key_metrics name. Screener is
# the reliable INDIA source (reachable from the VM; AV/yfinance are not).
_SCREENER_MAP: dict[str, str] = {
    "stock_p_e": "pe_ratio",
    "book_value": "book_value",
    "dividend_yield": "dividend_yield",
    "roce": "roce",
    "roe": "roe",
    "current_price": "current_price",
}


def _is_indian(symbols: list[str], resolved: dict[str, Any]) -> bool:
    exch = (resolved.get("exchange") or "").upper()
    if "NSE" in exch or "BSE" in exch:
        return True
    return any(s.upper().endswith((".NS", ".BO")) for s in symbols)


async def _screener_overview(symbols: list[str], resolved: dict[str, Any]) -> dict[str, Any]:
    """Live fundamentals for an Indian name via screener.in (VM-reachable)."""
    from pfip.ingest.indian_equities.screener_fundamentals import _fetch_page, _parse_ratios

    seen: set[str] = set()
    for s in symbols:
        base = s.split(".")[0].strip().upper()
        if not base or base in seen:
            continue
        seen.add(base)
        try:
            html = await _fetch_page(base)
        except Exception as e:  # noqa: BLE001
            log.warning(f"screener {base} failed: {type(e).__name__}: {e}")
            continue
        ratios = _parse_ratios(html)
        if not ratios:
            continue
        metrics: dict[str, Any] = {}
        for sk, canon in _SCREENER_MAP.items():
            if sk in ratios:
                # Screener reports ROE/ROCE/yield as PERCENTAGES (38.8) — keep
                # them that way. Percent is the app-wide convention: finnhub
                # (ROE 146.69) and the nightly screener ingest (ROCE 10.3) both
                # emit percent, and a /100 here made the SAME company show
                # roce 0.388 on /research but 38.8 on /diligence.
                metrics[canon] = ratios[sk]
        # Screener market cap is in ₹ crore → absolute ₹ for consistent formatting.
        if "market_cap" in ratios:
            metrics["market_cap"] = ratios["market_cap"] * 1e7
        if not metrics:
            continue
        return {
            "source": "screener",
            "matched_symbol": f"{base}.NS",
            "name": resolved.get("company"),
            "description": None,
            "sector": None,
            "industry": None,
            "exchange": "NSE",
            "currency": "INR",
            "key_metrics": metrics,
        }
    return {}


def _yfinance_overview_sync(symbols: list[str]) -> dict[str, Any]:
    """Synchronous yfinance ``.info`` pull — run in a worker thread."""
    import yfinance as yf

    for sym in symbols:
        try:
            info = yf.Ticker(sym).info or {}
        except Exception:  # noqa: BLE001
            continue
        if not info or not (info.get("longName") or info.get("shortName")):
            continue
        m: dict[str, Any] = {}
        mapping = {
            "pe_ratio": ("trailingPE", "forwardPE"),
            "pb_ratio": ("priceToBook",),
            "price_to_sales": ("priceToSalesTrailing12Months",),
            "operating_margin": ("operatingMargins",),
            "net_margin": ("profitMargins",),
            "roe": ("returnOnEquity",),
            "roa": ("returnOnAssets",),
            "revenue_growth": ("revenueGrowth",),
            "eps_growth": ("earningsGrowth",),
            "market_cap": ("marketCap",),
            "dividend_yield": ("dividendYield",),
            "beta": ("beta",),
            "book_value": ("bookValue",),
            "eps": ("trailingEps",),
            "52w_high": ("fiftyTwoWeekHigh",),
            "52w_low": ("fiftyTwoWeekLow",),
            "current_price": ("currentPrice", "regularMarketPrice"),
        }
        for canon, names in mapping.items():
            for n in names:
                v = info.get(n)
                if isinstance(v, (int, float)):
                    # yfinance .info reports margins/returns/growth/yield as
                    # fractions — normalise to the app-wide percent convention.
                    m[canon] = round(float(v) * 100.0, 4) if canon in _FRACTION_TO_PCT else float(v)
                    break
        return {
            "source": "yfinance",
            "matched_symbol": sym,
            "name": info.get("longName") or info.get("shortName"),
            "description": info.get("longBusinessSummary"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "key_metrics": m,
        }
    return {}


def _yfinance_perf_sync(symbols: list[str]) -> dict[str, Any] | None:
    """Best-effort 1M/3M/1Y price performance from yfinance daily history."""
    import yfinance as yf

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=400)
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(
                start=start.date().isoformat(), end=end.date().isoformat()
            )
        except Exception:  # noqa: BLE001
            continue
        if hist is None or hist.empty or "Close" not in hist:
            continue
        closes = [(ts.to_pydatetime(), float(c)) for ts, c in hist["Close"].items()]
        if len(closes) < 2:
            continue
        last_t, last = closes[-1]

        def _ret(days: int) -> float | None:
            cutoff = last_t - timedelta(days=days)
            prior = [c for t, c in closes if t.replace(tzinfo=None) <= cutoff.replace(tzinfo=None)]
            base = prior[-1] if prior else closes[0][1]
            return round((last - base) / base * 100, 1) if base else None

        return {
            "last_close": round(last, 2),
            "as_of": last_t.isoformat(),
            "ret_1m_pct": _ret(30),
            "ret_3m_pct": _ret(90),
            "ret_1y_pct": _ret(365),
            "bars": len(closes),
            "source": "yfinance",
        }
    return None


async def fetch_live_fundamentals(symbols: list[str], resolved: dict[str, Any]) -> dict[str, Any]:
    """Fetch live fundamentals for an untracked company. Never raises; ``{}`` on miss.

    Returns ``{source, matched_symbol, name, description, sector, industry,
    exchange, currency, key_metrics}`` — ``key_metrics`` keyed exactly like
    ``diligence._extract_key_metrics``.
    """
    # India: screener.in first — it's the only fundamentals source reachable from
    # the VM for Indian names (AV barely covers them; Yahoo 429s the datacenter IP).
    if _is_indian(symbols, resolved):
        sc = await _screener_overview(symbols, resolved)
        if sc.get("key_metrics"):
            return sc

    av = await _alphavantage_overview(symbols, resolved)
    if av.get("key_metrics"):
        return av

    # Fallback: yfinance (synchronous → worker thread). Covers NSE names AV misses.
    try:
        import anyio

        yfo = await anyio.to_thread.run_sync(lambda: _yfinance_overview_sync(symbols))
    except Exception as e:  # noqa: BLE001
        log.warning(f"yfinance overview failed: {type(e).__name__}: {e}")
        yfo = {}
    # If AV gave us metadata but no metrics, prefer yfinance metrics + keep AV blurb.
    if yfo.get("key_metrics"):
        if av and not yfo.get("description"):
            yfo["description"] = av.get("description")
        return yfo
    return av or yfo


async def persist_live_fundamentals(session: Any, live: dict[str, Any]) -> int:
    """Best-effort upsert of a live-fetched fundamentals dict so repeat searches
    accumulate history. Stores each canonical metric under its own field name
    keyed by the matched symbol. Never raises; returns rows written (0 on skip).
    """
    sym = (live or {}).get("matched_symbol")
    metrics = (live or {}).get("key_metrics") or {}
    if not sym or not metrics:
        return 0
    from datetime import date

    from pfip.ingest._common.upsert import upsert_fundamentals

    today = date.today()
    rows = [
        {
            "as_of_date": today,
            "report_date": today,
            "symbol": str(sym).upper(),
            "field": k,
            "value": v,
            "source": live.get("source") or "live",
        }
        for k, v in metrics.items()
        if v is not None
    ]
    try:
        return await upsert_fundamentals(session, rows)
    except Exception as e:  # noqa: BLE001 — persistence is a bonus, never blocks
        log.warning(f"persist_live_fundamentals failed: {type(e).__name__}: {e}")
        return 0


async def fetch_live_performance(symbols: list[str]) -> dict[str, Any] | None:
    """Best-effort live 1M/3M/1Y price performance (yfinance). ``None`` on miss."""
    try:
        import anyio

        return await anyio.to_thread.run_sync(lambda: _yfinance_perf_sync(symbols))
    except Exception as e:  # noqa: BLE001
        log.warning(f"yfinance perf failed: {type(e).__name__}: {e}")
        return None


__all__ = ["fetch_live_fundamentals", "fetch_live_performance"]
