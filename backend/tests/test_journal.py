"""Journal router smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_entries_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/journal/entries")
    assert resp.status_code == 401


def test_entries_empty_with_auth(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/journal/entries", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_entry_enforces_checklist(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/journal/entries",
        headers=auth_headers,
        json={
            "symbol": "BTC-USD",
            "direction": "BUY",
            "thesis": "test",
            "pre_trade_checklist": {},  # missing required keys
        },
    )
    assert resp.status_code == 422
