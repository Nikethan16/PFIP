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


def test_delete_entry_requires_auth(client: TestClient) -> None:
    resp = client.delete("/api/v1/journal/entries/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 401


def test_delete_missing_entry_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    # The smoke-test session yields no rows, so any id resolves to "not found".
    resp = client.delete(
        "/api/v1/journal/entries/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404
