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
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
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
                    m[canon] = float(v)
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


async def fetch_live_performance(symbols: list[str]) -> dict[str, Any] | None:
    """Best-effort live 1M/3M/1Y price performance (yfinance). ``None`` on miss."""
    try:
        import anyio

        return await anyio.to_thread.run_sync(lambda: _yfinance_perf_sync(symbols))
    except Exception as e:  # noqa: BLE001
        log.warning(f"yfinance perf failed: {type(e).__name__}: {e}")
        return None


__all__ = ["fetch_live_fundamentals", "fetch_live_performance"]
