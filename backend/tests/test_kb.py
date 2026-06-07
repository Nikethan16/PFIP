"""Tests for KB search / citation formatting.

These tests mock the Qdrant client + embed call; they do not require an
actual vector DB or Ollama. They cover:

- min-score filtering
- citation formatting (book vs news)
- graceful degradation when embed is unavailable
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from pfip.kb.search import KBHit, format_citations, search


def test_kbhit_citation_book() -> None:
    hit = KBHit(
        text="chunk",
        score=0.87,
        metadata={
            "source_type": "book",
            "title": "Expected Returns",
            "author": "Antti Ilmanen",
            "chapter": "Ch.3",
        },
    )
    cit = hit.citation
    assert "Expected Returns" in cit
    assert "Ilmanen" in cit
    assert "Ch.3" in cit


def test_kbhit_citation_news() -> None:
    hit = KBHit(
        text="chunk",
        score=0.71,
        metadata={
            "source_type": "news",
            "title": "RBI holds repo at 6.5%",
            "url": "https://example.com/rbi",
        },
    )
    cit = hit.citation
    assert "RBI" in cit
    assert "https://example.com/rbi" in cit


def test_format_citations_empty() -> None:
    assert "No sources" in format_citations([])


def test_format_citations_renders_bullets() -> None:
    hits = [
        KBHit(text="a", score=0.90, metadata={"title": "Book A", "author": "X"}),
        KBHit(text="b", score=0.72, metadata={"title": "Book B", "author": "Y"}),
    ]
    out = format_citations(hits)
    assert "Book A" in out
    assert "Book B" in out
    assert "score=0.90" in out


@pytest.mark.asyncio
async def test_search_filters_below_threshold() -> None:
    """Hits with score below MIN_SCORE_KB must be dropped."""
    import sys
    import importlib

    _search_mod = importlib.import_module("pfip.kb.search")
    # Re-bind so the module isn't shadowed by the re-exported function.
    sys.modules["pfip.kb.search"] = _search_mod

    fake_points = [
        SimpleNamespace(score=0.95, payload={"text": "good chunk", "title": "A"}),
        SimpleNamespace(score=0.40, payload={"text": "junk chunk", "title": "B"}),
    ]
    fake_client = SimpleNamespace(search=AsyncMock(return_value=fake_points))

    with (
        patch.object(_search_mod, "_embed", AsyncMock(return_value=[0.1] * 8)),
        patch.object(_search_mod, "get_qdrant", return_value=fake_client),
    ):
        hits = await _search_mod.search("test query", k=5)

    assert len(hits) == 1
    assert hits[0].metadata["title"] == "A"


@pytest.mark.asyncio
async def test_search_returns_empty_when_embed_unavailable() -> None:
    """If embed returns None, search must return an empty list (graceful)."""
    import importlib

    _search_mod = importlib.import_module("pfip.kb.search")
    with patch.object(_search_mod, "_embed", AsyncMock(return_value=None)):
        hits = await _search_mod.search("anything")
    assert hits == []
