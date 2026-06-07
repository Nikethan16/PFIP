"""Assets router smoke tests.

All assets endpoints are gated by ``CurrentUser`` (consistent with the other
routers), so each test passes ``auth_headers`` and we additionally assert that
an unauthenticated request is rejected with 401.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_candles_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/candles?timeframe=1d")
    assert resp.status_code == 401


def test_candles_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/candles?timeframe=1d", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_features_empty_well_formed(client: TestClient, auth_headers: dict[str, str]) -> None:
    # No feature rows in the fake session ⇒ well-formed empty payload (not 501).
    resp = client.get("/api/v1/assets/BTC/USD/features", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "BTC/USD"
    assert body["as_of"] is None
    assert body["features"]["rsi_14"] is None
    assert body["extras"] == {}


def test_news_empty_list(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/news", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_regime_unknown_when_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/regime", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["regime"] == "unknown"
    assert body["confidence"] == 0.0
