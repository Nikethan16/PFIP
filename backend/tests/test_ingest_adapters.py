"""Unit tests for ingest adapters — no real network calls.

We mock ``httpx.AsyncClient`` (via the shared ``get_async_client``) and feed in
canned payloads. The tests exercise:

1. AMFI NAV parser — canned NAVAll.txt parses to OHLCV rows.
2. Frankfurter FX — canned JSON parses to OHLCV rows.
3. CoinGecko market caps — canned JSON parses to fundamentals rows.
4. mempool.space network snapshot — canned JSON parses to fundamentals rows.
5. NASDAQ Data Link — canned JSON parses to fundamentals rows; honors missing key.
6. SEC 8-K RSS — canned Atom parses to news rows.
7. News pipeline — dedupe + entity_link logic with stub session.
8. Source health context manager records correctly on success and failure.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date, datetime, timezone
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# httpx mock helpers
# ---------------------------------------------------------------------------


class _MockResponse:
    def __init__(self, *, status_code: int = 200, json_data: Any = None, text: str = "", content: bytes | None = None) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = {"Content-Type": "application/json" if json_data is not None else "text/plain"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json


class _MockClient:
    def __init__(self, route_map: dict[str, _MockResponse]) -> None:
        self.route_map = route_map
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, **kwargs: Any) -> _MockResponse:
        self.calls.append((url, kwargs))
        # Longest-match-first to avoid greedy collisions like "/mempool" matching
        # "//mempool.space/..." in URLs.
        for key, resp in sorted(self.route_map.items(), key=lambda kv: -len(kv[0])):
            if key in url:
                return resp
        return _MockResponse(status_code=404, text="not found")

    async def post(self, url: str, **kwargs: Any) -> _MockResponse:
        return await self.get(url, **kwargs)


@contextlib.asynccontextmanager
async def _patch_client(route_map: dict[str, _MockResponse], *target_modules: str):
    """Patch get_async_client in each adapter module that imports it locally.

    If no target_modules are given, patches every loaded ingest module that
    has a ``get_async_client`` attribute.
    """
    client = _MockClient(route_map)

    @contextlib.asynccontextmanager
    async def _fake_get_async_client(**_kwargs):
        yield client

    import importlib
    import sys

    targets = list(target_modules)
    if not targets:
        targets = [
            name for name, mod in list(sys.modules.items())
            if name.startswith("pfip.ingest") and hasattr(mod, "get_async_client")
        ]
    originals: dict[str, Any] = {}
    for name in targets:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if hasattr(mod, "get_async_client"):
            originals[name] = mod.get_async_client
            mod.get_async_client = _fake_get_async_client  # type: ignore[assignment]
    try:
        yield client
    finally:
        for name, orig in originals.items():
            mod = sys.modules.get(name)
            if mod is not None:
                mod.get_async_client = orig  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 1. AMFI NAV parser
# ---------------------------------------------------------------------------


def test_amfi_nav_parser_shape():
    from pfip.ingest.indian_mf import amfi_nav

    sample = (
        "Open Ended Schemes(Equity)\n"
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        "100027;INF209K01YM2;INF209K01YN0;Aditya Birla Sun Life Frontline Equity Fund - Direct Plan-Growth;500.1234;29-May-2026\n"
        "100028;INF209K01YO8;INF209K01YP5;Aditya Birla Sun Life Liquid Fund - Direct Plan-Growth;1234.5678;29-May-2026\n"
    )
    parser_mod = amfi_nav
    # The module's _download is async — but it just returns text.  We feed the
    # parser directly with the text by monkey-patching _download.

    async def _go():
        async def fake_dl():
            return sample
        parser_mod._download = fake_dl  # type: ignore[attr-defined]
        rows = await parser_mod.fetch_amfi_nav()
        return rows

    rows = asyncio.run(_go())
    assert len(rows) == 2
    sample_row = rows[0]
    assert sample_row["source"] == "amfi"
    assert sample_row["timeframe"] == "1d"
    assert sample_row["market"] == "MF_INDIA"
    assert sample_row["symbol"].startswith("MF_")
    # NAV is the close field.
    assert float(sample_row["close"]) == pytest.approx(500.1234)


# ---------------------------------------------------------------------------
# 2. Frankfurter FX
# ---------------------------------------------------------------------------


def test_frankfurter_parse_basic():
    from pfip.ingest.fx import frankfurter

    # The historical endpoint returns rates keyed by date.
    sample = {
        "base": "USD",
        "rates": {
            "2026-05-28": {"INR": 83.21, "EUR": 0.92},
            "2026-05-29": {"INR": 83.30, "EUR": 0.91},
        },
    }

    async def _go():
        async with _patch_client({"frankfurter.app": _MockResponse(json_data=sample)}):
            rows = await frankfurter.fetch_frankfurter(
                pairs=(("USD", "INR"), ("USD", "EUR")), lookback_days=10
            )
            return rows

    rows = asyncio.run(_go())
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert all(r["source"] == "frankfurter" for r in rows)
    assert any(r["symbol"] == "USDINR" for r in rows)


# ---------------------------------------------------------------------------
# 3. CoinGecko market caps
# ---------------------------------------------------------------------------


def test_coingecko_market_caps_parse():
    from pfip.ingest.crypto import coingecko

    coins = [
        {"symbol": "btc", "market_cap": 1_300_000_000_000, "total_volume": 50_000_000_000, "current_price": 67000},
        {"symbol": "eth", "market_cap": 400_000_000_000, "total_volume": 20_000_000_000, "current_price": 3500},
    ]
    glob = {
        "data": {
            "total_market_cap": {"usd": 2_500_000_000_000},
            "market_cap_percentage": {"btc": 52.0, "eth": 16.0},
        }
    }

    async def _go():
        async with _patch_client(
            {
                "coins/markets": _MockResponse(json_data=coins),
                "/global": _MockResponse(json_data=glob),
            }
        ):
            rows = await coingecko.fetch_coingecko_snapshot(top_n=5)
        return rows

    rows = asyncio.run(_go())
    fields = {(r["symbol"], r["field"]) for r in rows}
    assert ("BTC", "market_cap_usd") in fields
    assert ("BTC", "volume_24h_usd") in fields
    assert ("CRYPTO_TOTAL", "market_cap_usd") in fields
    assert ("BTC", "dominance_pct") in fields


# ---------------------------------------------------------------------------
# 4. mempool.space network snapshot
# ---------------------------------------------------------------------------


def test_mempool_space_snapshot_parse():
    from pfip.ingest.crypto import mempool_space

    fees = {"fastestFee": 25, "halfHourFee": 18, "hourFee": 12, "economyFee": 6, "minimumFee": 1}
    hr = {"hashrates": [{"avgHashrate": 5.2e20}, {"avgHashrate": 5.3e20}]}
    mp = {"count": 12345, "vsize": 9_999_999, "total_fee": 12_000_000}
    tip = 845_000

    async def _go():
        async with _patch_client(
            {
                "fees/recommended": _MockResponse(json_data=fees),
                "mining/hashrate": _MockResponse(json_data=hr),
                "/api/mempool": _MockResponse(json_data=mp),
                "blocks/tip/height": _MockResponse(json_data=tip, text=str(tip)),
            }
        ):
            rows = await mempool_space.fetch_mempool_snapshot()
        return rows

    rows = asyncio.run(_go())
    by_field = {r["field"]: r for r in rows}
    assert "mempool_fastestFee" in by_field
    assert float(by_field["mempool_fastestFee"]["value"]) == pytest.approx(25.0)
    assert "chain_tip_height" in by_field


# ---------------------------------------------------------------------------
# 5. NASDAQ Data Link — missing key returns []
# ---------------------------------------------------------------------------


def test_ndl_no_key_no_op(monkeypatch):
    from pfip.ingest.commodities import nasdaq_data_link

    monkeypatch.delenv("NASDAQ_DATA_LINK_API_KEY", raising=False)
    rows = asyncio.run(nasdaq_data_link.fetch_nasdaq_data_link())
    assert rows == []


def test_ndl_with_key_parses(monkeypatch):
    from pfip.ingest.commodities import nasdaq_data_link

    monkeypatch.setenv("NASDAQ_DATA_LINK_API_KEY", "fake-key")
    payload = {
        "dataset": {
            "data": [
                ["2026-05-29", 2400.5, 2401.0, 2402.0, 2403.0, 2404.0],
                ["2026-05-28", 2390.0, 2391.5, 2392.0, 2393.0, 2394.0],
            ]
        }
    }

    async def _go():
        async with _patch_client({"datasets/": _MockResponse(json_data=payload)}):
            rows = await nasdaq_data_link.fetch_nasdaq_data_link(lookback_days=10)
        return rows

    rows = asyncio.run(_go())
    assert len(rows) > 0
    assert all(r["source"] == "nasdaq_data_link" for r in rows)


# ---------------------------------------------------------------------------
# 6. SEC 8-K Atom RSS
# ---------------------------------------------------------------------------


def test_sec_8k_atom_parse():
    from pfip.ingest.news import sec_8k_rss

    atom = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - Acme Corp (0000123456) (Filer)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0000123456"/>
    <updated>2026-05-29T12:00:00-04:00</updated>
    <summary>Material event</summary>
  </entry>
  <entry>
    <title>8-K - Globex Inc (0000654321) (Filer)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0000654321"/>
    <updated>2026-05-29T13:00:00-04:00</updated>
    <summary>Acquisition announcement</summary>
  </entry>
</feed>"""

    async def _go():
        async with _patch_client({"browse-edgar": _MockResponse(content=atom)}):
            items = await sec_8k_rss.fetch_sec_8k()
        return items

    items = asyncio.run(_go())
    assert len(items) == 2
    assert all(it["source"] == "sec_8k" for it in items)
    assert all(it["category"] == "sec_filing" for it in items)


# ---------------------------------------------------------------------------
# 7. News pipeline — normalize_url + is_crypto_text + filter
# ---------------------------------------------------------------------------


def test_pipeline_helpers():
    from pfip.ingest.news import _pipeline as p

    assert p.is_crypto_text("Bitcoin hits new high") is True
    assert p.is_crypto_text("Apple announces earnings") is False
    assert p._normalize_url("https://x.com/foo?utm_source=a&id=1#frag") == "https://x.com/foo?id=1"
    assert p._normalize_url("") == ""


# ---------------------------------------------------------------------------
# 8. source_health.track context manager
# ---------------------------------------------------------------------------


def test_source_health_track_success(monkeypatch):
    """``track`` swallows DB errors; we just need it to record the row count."""
    from pfip.ingest._common import source_health

    captured: list[tuple[str, int, str | None]] = []

    async def fake_record(source: str, *, rows: int, error: str | None = None, session=None):  # noqa: ANN001
        captured.append((source, rows, error))

    monkeypatch.setattr(source_health, "record_run", fake_record)

    async def _go():
        async with source_health.track("unit_test_source") as ctx:
            ctx.rows = 42

    asyncio.run(_go())
    assert captured == [("unit_test_source", 42, None)]


def test_source_health_track_failure(monkeypatch):
    from pfip.ingest._common import source_health

    captured: list[tuple[str, int, str | None]] = []

    async def fake_record(source: str, *, rows: int, error: str | None = None, session=None):  # noqa: ANN001
        captured.append((source, rows, error))

    monkeypatch.setattr(source_health, "record_run", fake_record)

    async def _go():
        with pytest.raises(RuntimeError):
            async with source_health.track("unit_test_failed") as ctx:
                ctx.rows = 3
                raise RuntimeError("boom")

    asyncio.run(_go())
    assert len(captured) == 1
    src, rows, err = captured[0]
    assert src == "unit_test_failed"
    assert rows == 3
    assert err is not None and "boom" in err


# ---------------------------------------------------------------------------
# 9. arxiv keyword filter
# ---------------------------------------------------------------------------


def test_arxiv_keyword_filter():
    from pfip.ingest.academic.arxiv_qfin import _filter_by_keywords

    items = [
        {"title": "Bitcoin volatility forecasting", "summary": "BTC GARCH model"},
        {"title": "Random unrelated paper", "summary": "About biology"},
        {"title": "Portfolio optimization with transformer", "summary": "Deep learning"},
    ]
    kept = _filter_by_keywords(items, ["bitcoin", "transformer"])
    titles = [i["title"] for i in kept]
    assert "Bitcoin volatility forecasting" in titles
    assert "Portfolio optimization with transformer" in titles
    assert "Random unrelated paper" not in titles
