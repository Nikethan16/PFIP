"""Unit tests for the FX-rate ingest adapter — pure logic, no network.

Covers:
  1. Range-payload parsing -> (base, quote, rate, rate_date) rows.
  2. Latest-payload parsing (flat ``{"date": ..., "rates": {...}}`` shape).
  3. Multi-quote (USD->INR + USD->EUR) parsing.
  4. Date-range URL path + query-param construction.
  5. Mocked end-to-end ``ingest_fx_rates`` with a stub session (no httpx).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date
from typing import Any

import pytest

from pfip.ingest.macro import fx_rates

# ---------------------------------------------------------------------------
# 1. Range payload parsing
# ---------------------------------------------------------------------------


def test_parse_range_payload_usd_inr():
    payload = {
        "base": "USD",
        "rates": {
            "2026-01-02": {"INR": 84.2000},
            "2026-01-03": {"INR": 84.3500},
        },
    }
    rows = fx_rates.parse_rate_rows(payload, "USD")
    assert len(rows) == 2
    r0 = rows[0]
    # Exact columns the tax/MTM reader (fx_cost_basis) depends on.
    assert set(r0) == {"rate_date", "base", "quote", "rate", "source"}
    assert r0["base"] == "USD"
    assert r0["quote"] == "INR"
    assert r0["source"] == "frankfurter"
    by_date = {r["rate_date"]: r["rate"] for r in rows}
    assert by_date[date(2026, 1, 2)] == pytest.approx(84.2000)
    assert by_date[date(2026, 1, 3)] == pytest.approx(84.3500)
    assert all(isinstance(r["rate_date"], date) for r in rows)


# ---------------------------------------------------------------------------
# 2. Latest (flat) payload parsing
# ---------------------------------------------------------------------------


def test_parse_latest_flat_payload():
    payload = {"base": "USD", "date": "2026-06-05", "rates": {"INR": 83.9100}}
    rows = fx_rates.parse_rate_rows(payload, "USD")
    assert len(rows) == 1
    assert rows[0]["rate_date"] == date(2026, 6, 5)
    assert rows[0]["base"] == "USD"
    assert rows[0]["quote"] == "INR"
    assert rows[0]["rate"] == pytest.approx(83.9100)


# ---------------------------------------------------------------------------
# 3. Multi-quote parsing
# ---------------------------------------------------------------------------


def test_parse_multi_quote():
    payload = {
        "base": "USD",
        "rates": {"2026-01-02": {"INR": 84.2, "EUR": 0.92}},
    }
    rows = fx_rates.parse_rate_rows(payload, "USD")
    pairs = {(r["base"], r["quote"]): r["rate"] for r in rows}
    assert pairs[("USD", "INR")] == pytest.approx(84.2)
    assert pairs[("USD", "EUR")] == pytest.approx(0.92)


def test_parse_skips_bad_values_and_empty():
    assert fx_rates.parse_rate_rows({"base": "USD", "rates": {}}, "USD") == []
    payload = {
        "base": "USD",
        "rates": {
            "not-a-date": {"INR": 84.0},
            "2026-01-02": {"INR": None, "EUR": 0.9},
        },
    }
    rows = fx_rates.parse_rate_rows(payload, "USD")
    # bad date dropped; None rate dropped; valid EUR kept.
    assert len(rows) == 1
    assert rows[0]["quote"] == "EUR"


# ---------------------------------------------------------------------------
# 4. URL / query-param construction
# ---------------------------------------------------------------------------


def test_range_path_and_query_params():
    start, end = date(2025, 1, 1), date(2026, 1, 1)
    assert fx_rates.range_path(start, end) == "/2025-01-01..2026-01-01"
    assert fx_rates.latest_path() == "/latest"
    params = fx_rates.query_params("usd", ["inr", "eur"])
    assert params == {"from": "USD", "to": "INR,EUR"}


# ---------------------------------------------------------------------------
# 5. Mocked ingest_fx_rates — stub session, patched HTTP fetch (no network)
# ---------------------------------------------------------------------------


class _StubSession:
    """Minimal AsyncSession stand-in capturing upsert params."""

    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []
        self.commits = 0

    async def execute(self, _stmt: Any, params: dict[str, Any]) -> None:
        self.executed.append(params)

    async def commit(self) -> None:
        self.commits += 1


def test_ingest_fx_rates_latest_mocked(monkeypatch):
    payload = {"base": "USD", "date": "2026-06-05", "rates": {"INR": 83.91}}

    captured_paths: list[str] = []

    async def fake_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
        captured_paths.append(path)
        return payload

    # Patch the HTTP layer only — parsing + upsert run for real against the stub.
    monkeypatch.setattr(fx_rates, "_get", fake_get)
    session = _StubSession()

    async def _go():
        return await fx_rates.ingest_fx_rates(
            mode="latest", bases=["USD"], quotes=["INR"], session=session
        )

    n = asyncio.run(_go())
    assert n == 1
    assert captured_paths == ["/latest"]
    assert session.commits == 1
    row = session.executed[0]
    assert row["base"] == "USD"
    assert row["quote"] == "INR"
    assert row["rate_date"] == date(2026, 6, 5)
    assert row["rate"] == pytest.approx(83.91)
    assert row["source"] == "frankfurter"


def test_ingest_fx_rates_backfill_mocked(monkeypatch):
    payload = {
        "base": "USD",
        "rates": {
            "2026-01-02": {"INR": 84.2},
            "2026-01-03": {"INR": 84.3},
        },
    }
    captured_paths: list[str] = []

    async def fake_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
        captured_paths.append(path)
        return payload

    monkeypatch.setattr(fx_rates, "_get", fake_get)
    session = _StubSession()

    async def _go():
        return await fx_rates.ingest_fx_rates(
            mode="backfill", lookback_days=30, bases=["USD"], quotes=["INR"], session=session
        )

    n = asyncio.run(_go())
    assert n == 2
    # backfill hits the date-range endpoint, not /latest.
    assert captured_paths and ".." in captured_paths[0]
    assert all(r["base"] == "USD" and r["quote"] == "INR" for r in session.executed)
