"""NL orchestrator — deterministic tool selection + registry + router smoke."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pfip.agent.orchestrator import extract_symbol, select_tool
from pfip.agent.tools import REGISTRY, TOOL_SPECS


def test_extract_symbol_names_and_tickers() -> None:
    assert extract_symbol("explain bitcoin to me") == "BTC-USD"
    assert extract_symbol("what's the price of AAPL") == "AAPL"
    assert extract_symbol("tell me about TCS.NS") == "TCS.NS"
    assert extract_symbol("how did i do this year") is None


def test_select_tool_routes_intents() -> None:
    assert select_tool("explain bitcoin") == ("explain_asset", {"symbol": "BTC-USD"})
    assert select_tool("what's on my calendar")[0] == "get_calendar"
    assert select_tool("show my holdings")[0] == "get_holdings"
    assert select_tool("tax summary for 2023-24") == ("get_tax_summary", {"fy": "2023-24"})
    assert select_tool("research TCS.NS")[0] == "get_diligence"
    assert select_tool("how's my p&l")[0] == "get_recent_pnl"


def test_select_tool_no_match() -> None:
    assert select_tool("what is the meaning of life") is None


def test_new_engines_are_registered() -> None:
    for name in ("explain_asset", "get_calendar", "screen_stocks"):
        assert name in REGISTRY
    assert {s.name for s in TOOL_SPECS} >= {"explain_asset", "get_calendar", "screen_stocks"}


def test_tools_endpoint_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/agent/tools").status_code == 401


def test_tools_endpoint_lists_specs(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/agent/tools", headers=auth_headers)
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert "explain_asset" in names and "get_calendar" in names


def test_orchestrate_matches_and_runs(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/agent/orchestrate",
        headers=auth_headers,
        json={"message": "explain bitcoin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["tool"] == "explain_asset"
    assert body["args"] == {"symbol": "BTC-USD"}


def test_orchestrate_no_match_is_graceful(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/agent/orchestrate",
        headers=auth_headers,
        json={"message": "hello there"},
    )
    assert resp.status_code == 200
    assert resp.json()["matched"] is False
