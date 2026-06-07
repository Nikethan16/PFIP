"""Live-data tests for the assets features/news/regime endpoints.

The default ``_FakeSession`` (conftest) yields empty results, which exercises
the well-formed *empty* path. To exercise the *populated* path we override the
DB dependency with a tiny fake session that returns seeded ORM rows for the
specific query, then assert the response shape.

All three endpoints are gated by ``CurrentUser``; each test also asserts that an
unauthenticated request is rejected with 401.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from pfip.api.deps import get_db
from pfip.api.main import app
from pfip.models.features import FeatureRow
from pfip.models.news import NewsRow
from pfip.models.regime import RegimeRow


class _SeededScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _SeededResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return _SeededScalars(self._rows)


class _SeededSession:
    """Returns ``rows`` for every ``execute`` — enough for these single-table reads."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _SeededResult(self._rows)

    async def close(self) -> None:
        return None


def _override_with(rows: list):
    async def _fake_db():
        yield _SeededSession(rows)

    return _fake_db


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


def test_features_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/assets/BTC/USD/features").status_code == 401


def test_news_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/assets/BTC/USD/news").status_code == 401


def test_regime_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/assets/BTC/USD/regime").status_code == 401


# ---------------------------------------------------------------------------
# Populated paths
# ---------------------------------------------------------------------------


def test_features_returns_latest_row(client: TestClient, auth_headers: dict[str, str]) -> None:
    row = FeatureRow(
        time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        symbol="BTC/USD",
        source="coinbase",
        timeframe="1d",
        rsi_14=55.5,
        macd=1.2,
        macd_signal=0.9,
        macd_hist=0.3,
        atr_14=42.0,
        return_7d=0.05,
        volatility_30d=0.3,
        extras={"funding_rate": 0.01},
    )
    app.dependency_overrides[get_db] = _override_with([row])
    try:
        resp = client.get("/api/v1/assets/BTC/USD/features", headers=auth_headers)
    finally:
        app.dependency_overrides[get_db] = _override_with([])  # reset to empty
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "BTC/USD"
    assert body["source"] == "coinbase"
    assert body["as_of"].startswith("2026-06-01")
    assert body["features"]["rsi_14"] == 55.5
    assert body["features"]["volatility_30d"] == 0.3
    assert body["extras"] == {"funding_rate": 0.01}


def test_news_returns_items(client: TestClient, auth_headers: dict[str, str]) -> None:
    rows = [
        NewsRow(
            time=datetime(2026, 6, 5, tzinfo=timezone.utc),
            title="BTC rallies",
            url="https://example.com/a",
            source="newsapi",
            symbol="BTC/USD",
            sentiment=0.6,
            summary="up",
        ),
        NewsRow(
            time=datetime(2026, 6, 4, tzinfo=timezone.utc),
            title="BTC dips",
            url="https://example.com/b",
            source="newsapi",
            symbol="BTC/USD",
            sentiment=-0.2,
            summary="down",
        ),
    ]
    app.dependency_overrides[get_db] = _override_with(rows)
    try:
        resp = client.get("/api/v1/assets/BTC/USD/news?limit=10", headers=auth_headers)
    finally:
        app.dependency_overrides[get_db] = _override_with([])
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["title"] == "BTC rallies"
    assert body[0]["sentiment"] == 0.6
    assert body[0]["source"] == "newsapi"


def test_news_limit_bounds(client: TestClient, auth_headers: dict[str, str]) -> None:
    # limit must be ge=1 le=200 like the other endpoints.
    assert (
        client.get("/api/v1/assets/BTC/USD/news?limit=0", headers=auth_headers).status_code == 422
    )
    assert (
        client.get("/api/v1/assets/BTC/USD/news?limit=500", headers=auth_headers).status_code == 422
    )


def test_regime_returns_latest_label(client: TestClient, auth_headers: dict[str, str]) -> None:
    row = RegimeRow(
        symbol="BTC/USD",
        regime="bull_trend",
        since=datetime(2026, 6, 1, tzinfo=timezone.utc),
        confidence=0.82,
    )
    app.dependency_overrides[get_db] = _override_with([row])
    try:
        resp = client.get("/api/v1/assets/BTC/USD/regime", headers=auth_headers)
    finally:
        app.dependency_overrides[get_db] = _override_with([])
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "BTC/USD"
    assert body["regime"] == "bull_trend"
    assert body["confidence"] == 0.82
    assert body["since"].startswith("2026-06-01")
