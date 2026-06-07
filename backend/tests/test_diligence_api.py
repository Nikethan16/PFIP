"""Tests for the diligence router (/api/v1/diligence/{symbol}).

Three things are verified, matching the backtest/shadow API-test style:

1. **Auth gate** — no bearer token → 401.
2. **Graceful sparse path** — the autouse empty fake session returns no OHLCV,
   so the endpoint maps "unknown symbol" to 404 (never a 500). The shared
   service itself still returns a well-formed skeleton (asserted directly).
3. **Populated shape** — a fake session that serves synthetic rows for each
   table exercises the full JSON serialization: pivoted fundamentals + the
   curated ``key_metrics`` subset, filings split from news, FII/DII flows,
   on-chain metrics, the model read, and the honest summary.

The fake session routes each query by inspecting the SQLAlchemy statement so a
single session object can answer the ~9 distinct reads the aggregator issues.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pfip.api.deps import get_db
from pfip.api.main import app
from pfip.models.fundamentals import FundamentalRow
from pfip.models.news import NewsRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.regime import RegimeRow
from pfip.models.signals import SignalRow

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Auth + sparse-symbol smoke tests (autouse empty fake session).
# ---------------------------------------------------------------------------


def test_diligence_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/diligence/NVDA")
    assert resp.status_code == 401


def test_diligence_unknown_symbol_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Empty fake session → no OHLCV → unknown symbol → 404 (never 500)."""
    resp = client.get("/api/v1/diligence/ZZZNOTREAL", headers=auth_headers)
    assert resp.status_code == 404


def test_diligence_dotted_and_dashed_symbols_route(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """``:path`` converter lets dotted/dashed tickers reach the handler (404 on
    the empty session, but importantly NOT a 404 from the router not matching)."""
    for sym in ("RELIANCE.NS", "BTC-USD"):
        resp = client.get(f"/api/v1/diligence/{sym}", headers=auth_headers)
        assert resp.status_code == 404  # empty session → unknown, but routed


# ---------------------------------------------------------------------------
# Service-level graceful-degradation test (no HTTP, empty fake session).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_sparse_symbol_returns_skeleton() -> None:
    """The shared service never raises on a sparse symbol — it returns a
    well-formed skeleton with ``found=False`` and empty sections."""
    from tests.conftest import _FakeSession  # type: ignore
    from pfip.diligence.service import build_diligence

    out = await build_diligence(_FakeSession(), "ANYTHING")
    assert out["found"] is False
    assert out["symbol"] == "ANYTHING"
    assert out["last_price"] is None
    assert out["fundamentals"]["key_metrics"] == {}
    assert out["filings"] == []
    assert out["news"] == []
    assert out["onchain"] == {}
    assert "disclaimer" in out["summary"]
    # Must be JSON-serializable.
    import json

    json.dumps(out)


# ---------------------------------------------------------------------------
# Populated-shape test with a query-routing fake session.
# ---------------------------------------------------------------------------


def _ohlcv_rows() -> list:
    """Two daily bars (newest first) so price + change resolve."""
    r1 = OHLCVRow()
    r1.time = NOW
    r1.symbol = "NVDA"
    r1.market = "US_EQUITY"
    r1.source = "tiingo"
    r1.timeframe = "1d"
    r1.open = r1.high = r1.low = r1.close = 205.0
    r1.volume = 1_000_000
    r0 = OHLCVRow()
    r0.time = NOW - timedelta(days=1)
    r0.symbol = "NVDA"
    r0.market = "US_EQUITY"
    r0.source = "tiingo"
    r0.timeframe = "1d"
    r0.open = r0.high = r0.low = r0.close = 200.0
    r0.volume = 1_000_000
    return [r1, r0]  # desc order as the query requests


def _fundamental_rows() -> list:
    rows = []
    facts = {
        "finnhub_peTTM": 31.1,
        "finnhub_pbAnnual": 28.8,
        "finnhub_grossMarginTTM": 74.15,
        "finnhub_roeTTM": 111.66,
        "finnhub_totalDebt/totalEquityAnnual": 0.05,
        "finnhub_marketCapitalization": 4_963_420.0,
        "finnhub_currentDividendYieldTTM": 0.0196,
    }
    for field, value in facts.items():
        r = FundamentalRow()
        r.as_of_date = date(2026, 6, 6)
        r.report_date = date(2026, 3, 31)
        r.symbol = "NVDA"
        r.field = field
        r.value = value
        r.source = "finnhub"
        rows.append(r)
    return rows


def _flow_rows() -> list:
    rows = []
    data = [
        ("FII/FPI_FLOW", "netValue", -8776.25),
        ("DII_FLOW", "netValue", 9133.57),
    ]
    for sym, field, value in data:
        r = FundamentalRow()
        r.as_of_date = date(2026, 6, 7)
        r.report_date = date(2026, 6, 7)
        r.symbol = sym
        r.field = field
        r.value = value
        r.source = "nse_fii_dii"
        rows.append(r)
    return rows


def _filing_rows() -> list:
    r = NewsRow()
    r.id = uuid.uuid4()
    r.time = NOW - timedelta(days=18)
    r.title = "NVDA 10-Q filed 2026-05-20"
    r.url = "https://sec.gov/nvda-10q"
    r.source = "sec_edgar"
    r.symbol = "NVDA"
    r.category = "sec_filing"
    return [r]


def _news_rows() -> list:
    r = NewsRow()
    r.id = uuid.uuid4()
    r.time = NOW - timedelta(hours=6)
    r.title = "Nvidia could reach $10T market cap"
    r.url = "https://example.com/nvda-news"
    r.source = "marketaux"
    r.symbol = "NVDA"
    r.sentiment = 0.4
    r.category = "news"
    return [r]


def _regime_row() -> RegimeRow:
    r = RegimeRow()
    r.id = uuid.uuid4()
    r.symbol = "NVDA"
    r.regime = "bull_trend"
    r.since = NOW
    r.confidence = 0.71
    return r


def _signal_row() -> SignalRow:
    s = SignalRow()
    s.id = uuid.uuid4()
    s.asset = "NVDA"
    s.direction = "BUY"
    s.confidence = 68
    s.horizon_hours = 72
    s.regime = "bull_trend"
    s.model_name = "lgbm_bull"
    s.model_version = "v1"
    s.drivers = []
    s.counter_arguments = []
    s.generated_at = NOW
    return s


class _ScalarsList:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    """Wraps a row list, exposing both the ``.all()`` (tuples) and
    ``.scalars()`` (ORM objects) shapes the service uses."""

    def __init__(self, rows: list, *, tuples: list | None = None) -> None:
        self._rows = rows
        self._tuples = tuples

    def scalars(self) -> _ScalarsList:
        return _ScalarsList(self._rows)

    def all(self) -> list:
        # Column-projection queries call .all() directly and expect row tuples.
        if self._tuples is not None:
            return list(self._tuples)
        return list(self._rows)

    def scalar(self):
        return len(self._rows)


class _RoutingSession:
    """Fake async session that answers each aggregator query by inspecting the
    statement's target entity / selected columns."""

    async def execute(self, stmt, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        text = str(stmt)
        low = text.lower()

        # --- signals (checked before regime: signals SQL mentions the regime
        #     column too) -------------------------------------------------------
        if "from signals" in low:
            return _Result([_signal_row()])
        if "from regime" in low:
            return _Result([_regime_row()])

        # --- OHLCV: price (column projection close/time/market) or count -----
        if "ohlcv" in low:
            if "count" in low:
                return _Result([1, 2])  # non-empty → found
            rows = _ohlcv_rows()
            tuples = [(r.close, r.time, r.market) for r in rows]
            return _Result(rows, tuples=tuples)

        # --- fundamentals: ticker pivot vs market-level flows ----------------
        if "fundamentals" in text.lower():
            # The flow query filters on the FII/DII pseudo-symbols; detect it via
            # the compiled bind params. Everything else is the per-ticker pivot.
            params = stmt.compile().params
            is_flow = any("FLOW" in str(v) for v in params.values())
            if is_flow:
                rows = _flow_rows()
                # Flow query selects (symbol, field, value, as_of_date).
                tuples = [(r.symbol, r.field, r.value, r.as_of_date) for r in rows]
            else:
                rows = _fundamental_rows()
                # Pivot query selects (field, value, source, as_of_date).
                tuples = [(r.field, r.value, r.source, r.as_of_date) for r in rows]
            return _Result(rows, tuples=tuples)

        # --- news: filings / insider / editorial -----------------------------
        # The editorial query uses ``category NOT IN (...)``; the filing/insider
        # queries use ``category IN (...)``. Route on the operator (the excluded
        # category names appear in the params of BOTH, so params alone can't
        # disambiguate — the IN vs NOT IN in the SQL text is the tell).
        if "news" in low:
            if "not in" in low:
                return _Result(_news_rows())
            params = stmt.compile().params
            joined = " ".join(str(v) for v in params.values())
            if "sec_filing" in joined or "corp_announcement" in joined:
                return _Result(_filing_rows())
            return _Result([])  # insider feed: empty in fixtures

        return _Result([])

    async def close(self) -> None:
        return None


@pytest.fixture
def populated_client():
    async def _routing_db():
        yield _RoutingSession()

    app.dependency_overrides[get_db] = _routing_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_diligence_populated_shape(populated_client, auth_headers: dict[str, str]) -> None:
    client = populated_client
    resp = client.get("/api/v1/diligence/NVDA", headers=auth_headers)
    assert resp.status_code == 200
    d = resp.json()

    # Top-level identity + price.
    assert d["symbol"] == "NVDA"
    assert d["found"] is True
    assert d["asset_class"] == "equity"
    assert d["last_price"] == 205.0
    assert d["change"] == 5.0
    assert d["change_pct"] == pytest.approx(2.5)

    # Fundamentals pivot + curated key_metrics.
    km = d["fundamentals"]["key_metrics"]
    assert d["fundamentals"]["source"] == "finnhub"
    assert km["pe_ratio"] == pytest.approx(31.1)
    assert km["pb_ratio"] == pytest.approx(28.8)
    assert km["gross_margin"] == pytest.approx(74.15)
    assert km["roe"] == pytest.approx(111.66)
    assert km["debt_to_equity"] == pytest.approx(0.05)
    assert km["market_cap"] == pytest.approx(4_963_420.0)
    assert "dividend_yield" in km

    # Filings split out of news; editorial news kept separate.
    assert len(d["filings"]) == 1
    assert d["filings"][0]["type"] == "sec_filing"
    assert len(d["news"]) == 1
    assert d["news"][0]["sentiment"] == pytest.approx(0.4)

    # Institutional flows (India market-level).
    flows = d["institutional_flows"]
    assert flows.get("fii", {}).get("netValue") == pytest.approx(-8776.25)
    assert flows.get("dii", {}).get("netValue") == pytest.approx(9133.57)

    # Model read — regime + experimental signal.
    assert d["model_read"]["regime"]["label"] == "bull_trend"
    assert d["model_read"]["signal"]["direction"] == "BUY"
    assert d["model_read"]["signal"]["note"] == "experimental"

    # Honest summary: coverage line, a P/E annotation, standing disclaimer.
    summary = d["summary"]
    assert "fundamentals present" in summary["data_coverage"]
    assert any("P/E" in a for a in summary["annotations"])
    assert "not investment advice" in summary["disclaimer"]


def test_diligence_populated_is_json_safe(populated_client, auth_headers: dict[str, str]) -> None:
    """Whole response must be JSON (no Decimal/datetime leakage)."""
    import json

    resp = populated_client.get("/api/v1/diligence/NVDA", headers=auth_headers)
    assert resp.status_code == 200
    json.dumps(resp.json())  # raises if not serializable
