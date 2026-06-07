"""Privacy-critical wiring tests for the Cohere reranker in the live agent.

The reranker sends the query + retrieved text to Cohere (cloud). It must
NEVER run for SENSITIVE queries. These tests prove two guarantees:

1. Unit-level: the real ``Reranker.rerank`` with ``sensitivity=SENSITIVE``
   returns identity order and NEVER touches the underlying client's cloud
   ``rerank`` method (no Cohere call).
2. Integration-level: ``run_agent_stream`` reranks PUBLIC queries (invoking
   the reranker, reordering hits) but for a SENSITIVE query the reranker is
   only ever called with ``sensitivity=SENSITIVE`` so no cloud call happens
   and identity order is preserved.

We follow the existing mocking style: monkeypatch node retrievers + the LLM
stream, and patch ``get_reranker`` in the graph module.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from pfip.agent import graph as _graph
from pfip.agent.reranker import Reranker, get_reranker
from pfip.agent.router import Sensitivity
from pfip.kb.search import KBHit


# ---------------------------------------------------------------------------
# Helpers — fake hits + a spy reranker / spy client
# ---------------------------------------------------------------------------


def _hit(text: str, score: float = 0.5) -> KBHit:
    return KBHit(text=text, score=score, metadata={"title": text})


class _SpyClient:
    """Stands in for MultiProviderClient. Records cloud rerank calls.

    ``rerank`` here represents the CLOUD (Cohere) call. If the privacy gate
    works, this is never invoked for SENSITIVE content.
    """

    def __init__(self) -> None:
        self.cloud_calls: list[tuple[str, list[str]]] = []

    async def rerank(self, query, docs, *, sensitivity=Sensitivity.PUBLIC):  # noqa: ANN001
        self.cloud_calls.append((query, list(docs)))
        # Reverse-relevance: later docs score higher → proves a reorder.
        n = len(docs)
        return [float(i) / max(1, n) for i in range(n)]


# ---------------------------------------------------------------------------
# 1. Unit: the real Reranker SENSITIVE gate never calls the cloud client
# ---------------------------------------------------------------------------


def test_real_reranker_sensitive_never_calls_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _SpyClient()
    r = Reranker()
    # Replace the bound client with our spy.
    r._client = spy  # type: ignore[attr-defined]

    docs = [_hit("a"), _hit("b"), _hit("c")]
    out = asyncio.run(r.rerank("q", docs, top_n=6, sensitivity=Sensitivity.SENSITIVE))

    # Identity order preserved (no reorder), and NO cloud call made.
    assert [r.doc.text for r in out] == ["a", "b", "c"]
    assert spy.cloud_calls == [], "SENSITIVE rerank must not hit the cloud client"


def test_real_reranker_public_calls_cloud_and_reorders() -> None:
    spy = _SpyClient()
    r = Reranker()
    r._client = spy  # type: ignore[attr-defined]

    docs = [_hit("a"), _hit("b"), _hit("c")]
    out = asyncio.run(r.rerank("q", docs, top_n=6, sensitivity=Sensitivity.PUBLIC))

    # Cloud WAS called for PUBLIC content.
    assert len(spy.cloud_calls) == 1
    # _SpyClient scores later docs higher → reversed order.
    assert [r.doc.text for r in out] == ["c", "b", "a"]


# ---------------------------------------------------------------------------
# Integration harness — drive run_agent_stream with mocked nodes
# ---------------------------------------------------------------------------


class _RerankSpy:
    """Records every (sensitivity) the graph hands to the reranker.

    Mirrors the real reranker's privacy gate so we can assert the graph
    passes the correct sensitivity AND that no cloud reorder happens when
    SENSITIVE.
    """

    def __init__(self) -> None:
        self.calls: list[Sensitivity] = []

    async def rerank(
        self, query, docs, *, top_n=None, sensitivity=Sensitivity.PUBLIC
    ):  # noqa: ANN001
        from pfip.agent.reranker import RerankResult

        self.calls.append(sensitivity)
        if sensitivity == Sensitivity.SENSITIVE:
            # No-op identity path — exactly like the real reranker; no cloud.
            return [RerankResult(doc=d, score=1.0 - (i / len(docs))) for i, d in enumerate(docs)]
        # PUBLIC: simulate a reorder (reverse) to prove the reranker ran.
        reordered = list(reversed(docs))
        return [RerankResult(doc=d, score=1.0 - (i / len(docs))) for i, d in enumerate(reordered)]


def _drive(monkeypatch: pytest.MonkeyPatch, *, kb_hits, query) -> tuple[_RerankSpy, list]:
    """Run the agent stream with retrieval mocked; return (spy, kb_titles_order)."""

    async def _fake_kb(state):
        state.retrieved_kb = list(kb_hits)
        return state

    async def _fake_news(state):
        state.retrieved_news = []
        return state

    async def _fake_db(_db, state):
        state.retrieved_db = []
        state.db_citations = []
        return state

    async def _fake_stream(*_a, **_k):
        yield "ok"

    class _FakeClient:
        async def stream(self, *_a, **_k):
            yield "ok"

    spy = _RerankSpy()

    monkeypatch.setattr(_graph, "node_retrieve_kb", _fake_kb)
    monkeypatch.setattr(_graph, "node_retrieve_news", _fake_news)
    monkeypatch.setattr(_graph, "node_retrieve_db", _fake_db)
    monkeypatch.setattr(_graph, "get_reranker", lambda: spy)
    monkeypatch.setattr(_graph, "get_llm_client", lambda: _FakeClient())

    async def _collect():
        sources: list = []
        async for ev in _graph.run_agent_stream(None, user_query=query, history=None):
            if ev["event"] == "source":
                sources.append(json.loads(ev["data"]).get("title"))
        return sources

    titles = asyncio.run(_collect())
    return spy, titles


# ---------------------------------------------------------------------------
# 2. Integration: PUBLIC query → reranker invoked + reorders
# ---------------------------------------------------------------------------


def test_public_query_invokes_reranker_and_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = [_hit("first"), _hit("second"), _hit("third")]
    # A clearly-public market query (no pronouns / holdings / tax nouns).
    spy, source_titles = _drive(monkeypatch, kb_hits=kb, query="explain MACD divergence on Nifty")

    assert spy.calls, "reranker should be invoked for a public query"
    assert all(
        s == Sensitivity.PUBLIC for s in spy.calls
    ), f"public query must rerank with PUBLIC sensitivity, got {spy.calls}"
    # PUBLIC path reversed the order → proves the reranker output was applied.
    assert source_titles == ["third", "second", "first"]


# ---------------------------------------------------------------------------
# 3. Integration: SENSITIVE query → reranker only ever sees SENSITIVE,
#    identity order preserved, NO cloud reorder.
# ---------------------------------------------------------------------------


def test_sensitive_query_never_reorders_via_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = [_hit("first"), _hit("second"), _hit("third")]
    # A clearly-sensitive query (personal pronoun + portfolio noun).
    spy, source_titles = _drive(
        monkeypatch, kb_hits=kb, query="how is my portfolio drawdown doing?"
    )

    assert spy.calls, "reranker should still be called (it self-gates) for sensitive query"
    assert all(
        s == Sensitivity.SENSITIVE for s in spy.calls
    ), f"sensitive query must pass SENSITIVE to reranker, got {spy.calls}"
    # Identity order preserved — the cloud reorder path was NOT taken.
    assert source_titles == ["first", "second", "third"]


def test_holdings_present_forces_sensitive_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a 'public-looking' query must rerank as SENSITIVE if a holding row
    is in the prompt — the 'holdings present => SENSITIVE' interlock must
    still gate the reranker."""
    kb = [_hit("first"), _hit("second")]

    async def _fake_kb(state):
        state.retrieved_kb = list(kb)
        return state

    async def _fake_news(state):
        state.retrieved_news = []
        return state

    async def _fake_db(_db, state):
        # A holding row present → must force SENSITIVE regardless of query text.
        state.retrieved_db = [{"kind": "holding", "symbol": "RELIANCE.NS"}]
        state.db_citations = ["db://holdings/1"]
        return state

    class _FakeClient:
        async def stream(self, *_a, **_k):
            yield "ok"

    spy = _RerankSpy()
    monkeypatch.setattr(_graph, "node_retrieve_kb", _fake_kb)
    monkeypatch.setattr(_graph, "node_retrieve_news", _fake_news)
    monkeypatch.setattr(_graph, "node_retrieve_db", _fake_db)
    monkeypatch.setattr(_graph, "get_reranker", lambda: spy)
    monkeypatch.setattr(_graph, "get_llm_client", lambda: _FakeClient())

    async def _collect():
        async for _ev in _graph.run_agent_stream(
            None, user_query="explain MACD divergence", history=None
        ):
            pass

    asyncio.run(_collect())
    assert spy.calls and all(
        s == Sensitivity.SENSITIVE for s in spy.calls
    ), f"holdings-present must force SENSITIVE rerank, got {spy.calls}"


# ---------------------------------------------------------------------------
# 4. Graceful degradation: rerank failure must not break the stream.
# ---------------------------------------------------------------------------


def test_rerank_failure_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = [_hit("first"), _hit("second")]

    class _BoomReranker:
        async def rerank(self, *_a, **_k):
            raise RuntimeError("cohere exploded")

    async def _fake_kb(state):
        state.retrieved_kb = list(kb)
        return state

    async def _fake_news(state):
        state.retrieved_news = []
        return state

    async def _fake_db(_db, state):
        state.retrieved_db = []
        state.db_citations = []
        return state

    class _FakeClient:
        async def stream(self, *_a, **_k):
            yield "ok"

    monkeypatch.setattr(_graph, "node_retrieve_kb", _fake_kb)
    monkeypatch.setattr(_graph, "node_retrieve_news", _fake_news)
    monkeypatch.setattr(_graph, "node_retrieve_db", _fake_db)
    monkeypatch.setattr(_graph, "get_reranker", lambda: _BoomReranker())
    monkeypatch.setattr(_graph, "get_llm_client", lambda: _FakeClient())

    async def _collect():
        events = []
        async for ev in _graph.run_agent_stream(
            None, user_query="explain MACD divergence", history=None
        ):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    # Stream still completes with a `done` event and original KB order intact.
    source_titles = [json.loads(e["data"]).get("title") for e in events if e["event"] == "source"]
    assert source_titles == ["first", "second"], "fallback must preserve original order"
    assert any(e["event"] == "done" for e in events), "stream must still finish on rerank failure"


def test_get_reranker_is_singleton() -> None:
    assert get_reranker() is get_reranker()
