"""Unit tests for on-demand live fundamentals (pfip.research.fundamentals)."""

from __future__ import annotations

import pytest

from pfip.research import fundamentals as F


def test_f_parses_av_none_string():
    assert F._f("None") is None
    assert F._f("") is None
    assert F._f(None) is None
    assert F._f("12.5") == 12.5
    assert F._f(3) == 3.0
    assert F._f("not-a-number") is None


def test_av_candidates_maps_indian_to_bse():
    cands = F._av_candidates(["RELIANCE.NS", "RELIANCE"], {})
    # Indian .NS → AV uses the .BSE suffix, then bare; bare RELIANCE de-duped.
    assert cands == ["RELIANCE.BSE", "RELIANCE"]


def test_av_candidates_us_is_bare_and_deduped():
    assert F._av_candidates(["AAPL", "AAPL"], {}) == ["AAPL"]


@pytest.mark.asyncio
async def test_alphavantage_overview_maps_metrics(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")

    async def fake_get(params):
        assert params["function"] == "OVERVIEW"
        return {
            "Symbol": "AAPL",
            "Name": "Apple Inc",
            "Description": "Designs phones.",
            "Sector": "Technology",
            "PERatio": "30.5",
            "PriceToBookRatio": "45.1",
            "ProfitMargin": "0.25",
            "MarketCapitalization": "3000000000000",
            "QuarterlyRevenueGrowthYOY": "None",  # AV's missing sentinel
        }

    monkeypatch.setattr(F, "_av_get", fake_get)
    out = await F._alphavantage_overview(["AAPL"], {})
    assert out["source"] == "alphavantage"
    assert out["name"] == "Apple Inc"
    km = out["key_metrics"]
    assert km["pe_ratio"] == 30.5
    assert km["pb_ratio"] == 45.1
    # AV reports ProfitMargin as a FRACTION (0.25); normalised to percent to
    # match the app-wide convention (finnhub/screener emit percent).
    assert km["net_margin"] == 25.0
    assert km["market_cap"] == 3_000_000_000_000
    assert "revenue_growth" not in km  # "None" dropped


@pytest.mark.asyncio
async def test_alphavantage_overview_no_key_returns_empty(monkeypatch):
    # alphavantage_key() accepts BOTH spellings, so "no key" must clear both —
    # otherwise a real ALPHA_VANTAGE_API_KEY in the loaded .env leaks in and the
    # function tries a live fetch instead of the intended no-op.
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert await F._alphavantage_overview(["AAPL"], {}) == {}


@pytest.mark.asyncio
async def test_alphavantage_rate_limit_stops(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")

    async def fake_get(params):
        return {"Information": "rate limited; 25/day exceeded"}

    monkeypatch.setattr(F, "_av_get", fake_get)
    assert await F._alphavantage_overview(["AAPL"], {}) == {}


def test_is_indian_detection():
    assert F._is_indian(["RELIANCE.NS"], {}) is True
    assert F._is_indian([], {"exchange": "BSE"}) is True
    assert F._is_indian(["AAPL"], {"exchange": "NASDAQ"}) is False


@pytest.mark.asyncio
async def test_screener_overview_normalizes_percent_and_crore(monkeypatch):
    """ROE/ROCE/yield kept as PERCENT (app-wide convention); market cap ₹cr →
    absolute ₹. Screener already reports these as percent, so /research and
    /diligence now read the SAME number for the same company."""

    async def fake_fetch_page(sym):
        return "<html>waree</html>"

    def fake_parse(_html):
        return {
            "stock_p_e": 21.0,
            "book_value": 502.0,
            "dividend_yield": 0.07,  # percent, kept as-is
            "roce": 38.8,  # percent, kept as-is
            "roe": 32.8,  # percent, kept as-is
            "current_price": 2859.0,
            "market_cap": 82245.0,  # ₹ crore → 8.2245e11
        }

    import pfip.ingest.indian_equities.screener_fundamentals as S

    monkeypatch.setattr(S, "_fetch_page", fake_fetch_page)
    monkeypatch.setattr(S, "_parse_ratios", fake_parse)

    out = await F._screener_overview(["WAAREEENER.NS", "WAAREEENER"], {"company": "Waaree"})
    km = out["key_metrics"]
    assert out["source"] == "screener"
    assert out["matched_symbol"] == "WAAREEENER.NS"
    assert km["pe_ratio"] == 21.0
    assert km["roce"] == pytest.approx(38.8)
    assert km["roe"] == pytest.approx(32.8)
    assert km["dividend_yield"] == pytest.approx(0.07)
    assert km["market_cap"] == pytest.approx(8.2245e11)


@pytest.mark.asyncio
async def test_fetch_live_indian_prefers_screener(monkeypatch):
    """Indian symbol → screener is tried before AV/yfinance."""

    async def fake_screener(symbols, resolved):
        return {"source": "screener", "key_metrics": {"pe_ratio": 21.0}}

    async def fail_av(symbols, resolved):  # must not be reached
        raise AssertionError("AV should not be called for Indian when screener wins")

    monkeypatch.setattr(F, "_screener_overview", fake_screener)
    monkeypatch.setattr(F, "_alphavantage_overview", fail_av)
    out = await F.fetch_live_fundamentals(["WAAREEENER.NS"], {"exchange": "NSE"})
    assert out["source"] == "screener"


@pytest.mark.asyncio
async def test_persist_live_fundamentals_builds_rows(monkeypatch):
    captured: dict[str, list] = {}

    async def fake_upsert(session, rows):
        captured["rows"] = list(rows)
        return len(captured["rows"])

    import pfip.ingest._common.upsert as U

    monkeypatch.setattr(U, "upsert_fundamentals", fake_upsert)
    live = {
        "source": "screener",
        "matched_symbol": "WAAREEENER.NS",
        "key_metrics": {"pe_ratio": 21.0, "roe": 0.328, "market_cap": None},
    }
    n = await F.persist_live_fundamentals(object(), live)
    assert n == 2  # None value dropped
    fields = {r["field"]: r for r in captured["rows"]}
    assert set(fields) == {"pe_ratio", "roe"}
    assert fields["pe_ratio"]["symbol"] == "WAAREEENER.NS"
    assert fields["pe_ratio"]["source"] == "screener"


@pytest.mark.asyncio
async def test_persist_live_fundamentals_skips_when_no_symbol():
    assert await F.persist_live_fundamentals(object(), {"key_metrics": {"pe_ratio": 1}}) == 0
    assert await F.persist_live_fundamentals(object(), {"matched_symbol": "X"}) == 0


@pytest.mark.asyncio
async def test_fetch_live_us_falls_back_to_yfinance(monkeypatch):
    """US name, AV returns nothing → yfinance overview is used (no screener)."""
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    def fake_yf(symbols):
        return {
            "source": "yfinance",
            "matched_symbol": symbols[0],
            "name": "Some US Co",
            "key_metrics": {"pe_ratio": 40.0, "roe": 0.22},
        }

    monkeypatch.setattr(F, "_yfinance_overview_sync", fake_yf)
    # US symbol → _is_indian False → screener never touched (no network).
    out = await F.fetch_live_fundamentals(["SOMEUSCO"], {"exchange": "NASDAQ"})
    assert out["source"] == "yfinance"
    assert out["key_metrics"]["pe_ratio"] == 40.0
