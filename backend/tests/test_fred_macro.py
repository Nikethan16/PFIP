"""FRED macro parsing (pfip.ingest.macro.fred).

Regression: the adapter stamped ``as_of_date=today`` on every observation, so
all dated points of a series collided on the ``(as_of_date, symbol, field,
source)`` conflict key and the whole series persisted as ONE latest value.
Each observation must key by its own date.
"""

from __future__ import annotations

from datetime import date

import pytest

from pfip.ingest.macro import fred as M


@pytest.mark.asyncio
async def test_no_key_is_noop(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert await M.fetch_fred_macro(["CPIAUCSL"]) == []


@pytest.mark.asyncio
async def test_observation_date_is_the_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "demo")

    async def fake_fetch(series_id, api_key, observation_start):
        return [
            {"date": "2026-05-01", "value": "310.1"},
            {"date": "2026-06-01", "value": "311.4"},
            {"date": "2026-07-01", "value": "."},  # FRED missing sentinel → dropped
        ]

    monkeypatch.setattr(M, "_fetch_series", fake_fetch)
    rows = await M.fetch_fred_macro(["CPIAUCSL"])

    # Two valid observations, each keyed by its OWN date (no collapse, no today()).
    assert len(rows) == 2
    for r in rows:
        assert r["as_of_date"] == r["report_date"]
        assert r["symbol"] == "CPIAUCSL"
        assert r["source"] == "fred"
    assert {r["as_of_date"] for r in rows} == {date(2026, 5, 1), date(2026, 6, 1)}
    assert {float(r["value"]) for r in rows} == {310.1, 311.4}


@pytest.mark.asyncio
async def test_series_failure_is_skipped_not_fatal(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "demo")

    async def boom(series_id, api_key, observation_start):
        raise RuntimeError("FRED 400")

    monkeypatch.setattr(M, "_fetch_series", boom)
    # One bad series must not raise — returns empty, pipeline continues.
    assert await M.fetch_fred_macro(["CPIAUCSL"]) == []
