"""Alpha Vantage EOD OHLCV adapter (pfip.ingest.us_equities.alphavantage_ohlcv).

This is the US gap-filler that keeps AAPL/NVDA current when Tiingo's quota is
spent and yfinance/stooq are IP-throttled from the VM.
"""

from __future__ import annotations

import pytest

from pfip.ingest.us_equities import alphavantage_ohlcv as AV


@pytest.mark.asyncio
async def test_no_key_is_noop(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert await AV.fetch_alphavantage_daily(["AAPL"]) == []


@pytest.mark.asyncio
async def test_parses_daily_series(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")

    async def fake_fetch(symbol, key):
        return {
            "Time Series (Daily)": {
                "2026-07-02": {
                    "1. open": "190.0",
                    "2. high": "193.5",
                    "3. low": "189.1",
                    "4. close": "192.5",
                    "5. volume": "51000000",
                },
                "2026-07-01": {
                    "1. open": "188.0",
                    "2. high": "191.0",
                    "3. low": "187.0",
                    "4. close": "190.2",
                    "5. volume": "48000000",
                },
            }
        }

    monkeypatch.setattr(AV, "_fetch_daily", fake_fetch)
    rows = await AV.fetch_alphavantage_daily(["AAPL"])
    assert len(rows) == 2
    r = next(x for x in rows if x["time"].date().isoformat() == "2026-07-02")
    assert r["symbol"] == "AAPL" and r["source"] == "alphavantage"
    assert r["market"] == "US_EQUITY" and r["timeframe"] == "1d"
    assert r["close"] == 192.5 and r["volume"] == 51000000.0


@pytest.mark.asyncio
async def test_rate_limit_stops_run(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")
    calls = {"n": 0}

    async def fake_fetch(symbol, key):
        calls["n"] += 1
        return {"Information": "25/day limit reached"}

    monkeypatch.setattr(AV, "_fetch_daily", fake_fetch)
    rows = await AV.fetch_alphavantage_daily(["AAPL", "NVDA", "MSFT"])
    # Hit the limit on the first symbol → stop, don't burn calls on the rest.
    assert rows == []
    assert calls["n"] == 1
