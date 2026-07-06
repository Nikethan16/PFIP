"""User-defined alerts — pure rule engine + router smoke."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pfip.alerts.rules import AlertRule, evaluate_rule


def test_price_above_triggers() -> None:
    r = AlertRule(symbol="AAPL", kind="price_above", threshold=180.0)
    ev = evaluate_rule(r, last_close=187.2, move_pct_1d=1.0)
    assert ev.triggered is True
    assert ev.current_value == 187.2


def test_price_below_not_triggered() -> None:
    r = AlertRule(symbol="AAPL", kind="price_below", threshold=180.0)
    ev = evaluate_rule(r, last_close=187.2, move_pct_1d=None)
    assert ev.triggered is False


def test_pct_down_triggers_on_drop() -> None:
    r = AlertRule(symbol="BTC-USD", kind="pct_down_1d", threshold=5.0)
    ev = evaluate_rule(r, last_close=100.0, move_pct_1d=-6.3)
    assert ev.triggered is True
    assert ev.current_value == -6.3


def test_pct_up_not_enough_history_is_untriggered() -> None:
    r = AlertRule(symbol="BTC-USD", kind="pct_up_1d", threshold=5.0)
    ev = evaluate_rule(r, last_close=100.0, move_pct_1d=None)
    assert ev.triggered is False
    assert ev.current_value is None
    assert "history" in ev.reason.lower()


def test_price_rule_without_price_is_untriggered() -> None:
    r = AlertRule(symbol="XYZ", kind="price_above", threshold=10.0)
    ev = evaluate_rule(r, last_close=None, move_pct_1d=None)
    assert ev.triggered is False
    assert ev.current_value is None


# --- router smoke -----------------------------------------------------------


def test_kinds_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/alerts/kinds").status_code == 401


def test_evaluate_returns_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Fake DB yields no OHLCV → price snapshots are None → nothing triggers,
    # but the response shape must be valid.
    resp = client.post(
        "/api/v1/alerts/evaluate",
        headers=auth_headers,
        json={"rules": [{"symbol": "AAPL", "kind": "price_above", "threshold": 1.0}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_triggered"] == 0
    assert len(body["results"]) == 1
    assert body["results"][0]["triggered"] is False
