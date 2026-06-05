"""Cohere reranker wrapper — no-op when COHERE_API_KEY isn't set.

Reranking lifts RAG quality more than swapping the chat LLM does (per
LLM_ROUTING.md §6). We call ``rerank-v3-english`` if Cohere is configured,
and degrade gracefully to identity ordering otherwise.

Typical use after Qdrant retrieval::

    hits = await kb_search(query, k=20)
    reranker = get_reranker()
    sorted_hits = await reranker.rerank(query, hits, top_n=5)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pfip.agent.llm_client import get_llm_client
from pfip.agent.router import Sensitivity


class _HasText(Protocol):
    text: str


T = TypeVar("T", bound=_HasText)


@dataclass(frozen=True, slots=True)
class RerankResult(Generic[T]):
    """A document plus its reranker score."""

    doc: T
    score: float


class Reranker:
    """Wraps ``MultiProviderClient.rerank``.

    The :meth:`rerank` method takes any list of objects with a ``.text``
    attribute (e.g. ``KBHit``) and returns them sorted by relevance to the
    query. When Cohere isn't configured, original order is preserved with
    descending dummy scores so callers can sort either way safely.
    """

    def __init__(self) -> None:
        self._client = get_llm_client()

    async def rerank(
        self,
        query: str,
        docs: list[T],
        *,
        top_n: int | None = None,
        sensitivity: Sensitivity = Sensitivity.PUBLIC,
    ) -> list[RerankResult[T]]:
        """Return ``docs`` sorted by descending relevance to ``query``.

        Cohere rerank-v3 is content-moderated and explicitly no-training-on-
        data on the free trial; safe for public market content. Holdings-
        bearing content should not be reranked via Cohere — pass
        ``sensitivity=Sensitivity.SENSITIVE`` and the caller is expected to
        skip the Cohere path. (Currently this still respects the no-op
        identity path when sensitive.)
        """
        if not docs:
            return []
        if sensitivity == Sensitivity.SENSITIVE:
            # Don't send sensitive content to Cohere even if a key is set.
            return [RerankResult(doc=d, score=1.0 - (i / len(docs))) for i, d in enumerate(docs)]
        texts = [d.text for d in docs]
        scores = await self._client.rerank(query, texts, sensitivity=sensitivity)
        paired = [RerankResult(doc=d, score=s) for d, s in zip(docs, scores, strict=False)]
        paired.sort(key=lambda r: r.score, reverse=True)
        if top_n is not None:
            paired = paired[:top_n]
        return paired


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


__all__ = ["Reranker", "RerankResult", "get_reranker"]
