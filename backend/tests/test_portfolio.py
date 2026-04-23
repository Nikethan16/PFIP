"""Portfolio router smoke tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "fixtures"


def test_holdings_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/portfolio/holdings")
    assert resp.status_code == 401


def test_holdings_empty_with_auth(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/portfolio/holdings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_import_unknown_schema_returns_400(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/v1/portfolio/import",
        files={"file": ("x.csv", b"a,b,c\n1,2,3\n", "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["error"] == "unknown_schema"


def test_import_zerodha_csv_dry_run_ok(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    data = (FIX / "zerodha_tradebook.csv").read_bytes()
    resp = client.post(
        "/api/v1/portfolio/import",
        files={"file": ("tb.csv", data, "text/csv")},
        data={"broker": "zerodha", "dry_run": "true"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["broker"] == "zerodha"
    assert body["imported"] >= 1
    assert "disclaimer" in body


def test_import_supported_list(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/portfolio/import/supported", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    brokers = {b["broker"] for b in body["brokers"]}
    # A few expected ones
    assert {"zerodha", "indmoney", "wazirx", "binance"}.issubset(brokers)


def test_pre_trade_endpoint_runs(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/portfolio/pre-trade",
        json={
            "symbol": "RELIANCE.NS",
            "qty": "10",
            "price": "2900",
            "portfolio_value_inr": "1000000",
            "stop_distance_pct": 0.03,
            "regime": "bull_trend",
            "signal_confidence": 65,
            "news_count_24h": 2,
            "event_calendar_conflict": False,
            "positions_added_today": 0,
            "current_drawdown_pct": 0.05,
            "existing_symbols": [],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "pass_all" in body
    assert "per_item" in body
    assert "disclaimer" in body


def test_summary_returns_portfolio_summary(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/portfolio/summary", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    # PortfolioSummary fields
    assert "total_inr" in body
    assert "pnl_inr" in body
    assert "exposure_by_category" in body
    assert "drawdown" in body
