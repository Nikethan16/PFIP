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
    assert km["net_margin"] == 0.25
    assert km["market_cap"] == 3_000_000_000_000
    assert "revenue_growth" not in km  # "None" dropped


@pytest.mark.asyncio
async def test_alphavantage_overview_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    assert await F._alphavantage_overview(["AAPL"], {}) == {}


@pytest.mark.asyncio
async def test_alphavantage_rate_limit_stops(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")

    async def fake_get(params):
        return {"Information": "rate limited; 25/day exceeded"}

    monkeypatch.setattr(F, "_av_get", fake_get)
    assert await F._alphavantage_overview(["AAPL"], {}) == {}


@pytest.mark.asyncio
async def test_fetch_live_falls_back_to_yfinance(monkeypatch):
    """AV returns nothing → yfinance overview is used."""
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)

    def fake_yf(symbols):
        return {
            "source": "yfinance",
            "matched_symbol": symbols[0],
            "name": "Waaree Energies",
            "key_metrics": {"pe_ratio": 40.0, "roe": 0.22},
        }

    monkeypatch.setattr(F, "_yfinance_overview_sync", fake_yf)
    out = await F.fetch_live_fundamentals(["WAAREEENER.NS"], {})
    assert out["source"] == "yfinance"
    assert out["key_metrics"]["pe_ratio"] == 40.0
