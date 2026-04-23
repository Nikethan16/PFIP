"""Signals router smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_signals_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/signals")
    assert resp.status_code == 401


def test_signals_empty_with_auth(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/signals", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_signals_latest_empty_with_auth(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/signals/latest", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []
