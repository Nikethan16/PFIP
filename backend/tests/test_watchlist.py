"""Watchlist router smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_watchlist_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/watchlist")
    assert resp.status_code == 401


def test_watchlist_list_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/watchlist", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []
