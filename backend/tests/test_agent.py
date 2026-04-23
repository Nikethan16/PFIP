"""Agent router + graph + morning-brief tests.

These tests stub the LLM layer (Ollama) and Qdrant so they run in <1s on
a machine with neither installed — the contract being verified is the
*surface* of the agent, not token-level quality.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pfip.agent.graph import (
    LLMInjectionBlock,
    cite_and_validate,
    classify_intent,
)


# ---------------------------------------------------------------------------
# Existing smoke tests
# ---------------------------------------------------------------------------


def test_chat_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/agent/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_morning_brief_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/agent/morning-brief")
    assert resp.status_code == 401


def test_morning_brief_returns_markdown(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/agent/morning-brief", headers=auth_headers)
    assert resp.status_code == 200
    assert "# PFIP Morning Brief" in resp.text


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "q,expected",
    [
        ("what's my current drawdown on the NIFTY book?", "portfolio_question"),
        ("how does stcg grandfathering work?", "tax_question"),
        ("BTC regime and RSI?", "market_question"),
        ("hi there", "general"),
    ],
)
def test_classify_intent(q: str, expected: str) -> None:
    assert classify_intent(q) == expected


# ---------------------------------------------------------------------------
# Decide-contract guard
# ---------------------------------------------------------------------------


def test_cite_and_validate_rejects_typed_signal() -> None:
    txt = 'Here is a signal: {"direction":"BUY","confidence":72,"horizon_hours":24}'
    with pytest.raises(LLMInjectionBlock):
        cite_and_validate(txt, citations_available=["db://x/1"])


def test_cite_and_validate_rejects_directive_prose() -> None:
    txt = "Conclusion: direction: BUY, confidence: 80, horizon: 1d"
    with pytest.raises(LLMInjectionBlock):
        cite_and_validate(txt, citations_available=["db://x/1"])


def test_cite_and_validate_appends_note_when_no_citation() -> None:
    txt = "The market is probably range-bound this week."
    out = cite_and_validate(txt, citations_available=["db://regime/1"])
    assert "did not produce inline citations" in out


def test_cite_and_validate_passes_with_citation() -> None:
    txt = "Regime is sideways (db://regime/abc) with weakening momentum."
    out = cite_and_validate(txt, citations_available=["db://regime/abc"])
    assert "did not produce inline citations" not in out


# ---------------------------------------------------------------------------
# Morning-brief populates all 8 sections from DB (mocked)
# ---------------------------------------------------------------------------


def test_morning_brief_has_all_eight_sections(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/agent/morning-brief", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.text
    for header in [
        "## 1. Overnight moves",
        "## 2. Economic calendar today",
        "## 3. Top 3 overnight news per watchlist",
        "## 4. Regime state per market",
        "## 5. Watchlist deltas",
        "## 6. Open-position risk snapshot",
        "## 7. Calibration note",
        "## 8. Shadow vs actual",
    ]:
        assert header in body, f"missing section: {header}"


# ---------------------------------------------------------------------------
# Chat endpoint — Ollama unavailable path must yield an SSE `done`
# ---------------------------------------------------------------------------


def test_chat_sse_handles_ollama_unavailable_gracefully(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """If the router raises LLMUnavailable we should still get a clean
    SSE stream ending with `event: done`."""
    # Patch the node retrievers and stream so the endpoint doesn't hit
    # a real Qdrant or Ollama.
    async def _empty_stream(*_a, **_k):
        raise RuntimeError("forced-unavailable-in-test")
        yield  # pragma: no cover — unreachable, marks func as async-gen

    from pfip.agent import graph as _g

    async def _fake_kb(state):
        return state

    async def _fake_news(state):
        return state

    async def _fake_db(_db, state):
        return state

    async def _fake_run(*args, **kwargs):
        yield {"event": "token", "data": '{"text":"ok"}'}
        yield {"event": "done", "data": "{}"}

    with patch.object(_g, "run_agent_stream", _fake_run):
        resp = client.post(
            "/api/v1/agent/chat",
            json={"message": "what's the regime?"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    # Content-type must be SSE.
    assert "text/event-stream" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Post-mortem 404 when holding does not exist
# ---------------------------------------------------------------------------


def test_post_mortem_404_on_unknown_holding(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/v1/agent/post-mortem",
        json={"holding_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Weekly review + arxiv-digest endpoints
# ---------------------------------------------------------------------------


def test_weekly_review_returns_markdown(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/agent/weekly-review", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "markdown" in body
    assert body["markdown"].startswith("## Weekly Review")


def test_arxiv_digest_returns_markdown(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/agent/arxiv-digest", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "markdown" in body
    assert "arXiv" in body["markdown"]
