"""Assets router smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_candles_empty(client: TestClient) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/candles?timeframe=1d")
    assert resp.status_code == 200
    assert resp.json() == []


def test_features_stub(client: TestClient) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/features")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_news_stub_501(client: TestClient) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/news")
    assert resp.status_code == 501


def test_regime_stub_501(client: TestClient) -> None:
    resp = client.get("/api/v1/assets/BTC/USD/regime")
    assert resp.status_code == 501
