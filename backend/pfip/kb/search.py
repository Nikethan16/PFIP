"""Knowledge-base RAG search — embed query, search Qdrant, format citations.

Two collections are queried:

- ``kb`` — chunked book content (Section 10 of the plan).
- ``news`` — recent news items (populated by ``pfip.kb.news_embed``).

Public functions:

- :func:`search` / :func:`search_news` — retrieve top-``k`` hits above a
  minimum cosine-similarity threshold. The threshold (``0.6`` default) is
  deliberately aggressive so hallucinations don't get "grounded" by junk
  chunks.
- :func:`format_citations` — render a Markdown citation block the agent can
  append to its response.

No Qdrant import is done at module import time beyond the client package;
real network use happens lazily inside the functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from pfip.agent.llm_client import LLMUnavailable, get_llm_router
from pfip.core.config import get_settings

# --- Tunables --------------------------------------------------------------
MIN_SCORE_KB = 0.60  # cosine; tighter floor because books are long-form
MIN_SCORE_NEWS = 0.55  # slightly softer for news (shorter snippets)
KB_COLLECTION = "kb"
NEWS_COLLECTION = "news"


@dataclass(frozen=True, slots=True)
class KBHit:
    """A single retrieval hit."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        """Markdown-friendly short citation."""
        meta = self.metadata or {}
        if meta.get("source_type") == "news":
            title = meta.get("title", "news")
            url = meta.get("url", "")
            return f"[{title}]({url})" if url else title
        title = meta.get("title", "?")
        author = meta.get("author", "?")
        chapter = meta.get("chapter") or meta.get("page_range") or ""
        suffix = f", {chapter}" if chapter else ""
        return f"*{title}* — {author}{suffix}"


# --- Client singleton ------------------------------------------------------

_client: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    """Async Qdrant client, configured from settings."""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url)
    return _client


async def _embed(query: str) -> list[float] | None:
    """Embed the query via Ollama nomic-embed-text. Returns None on failure."""
    try:
        return await get_llm_router().embed(query)
    except LLMUnavailable as exc:
        logger.warning(f"Embedding unavailable; KB search degraded: {exc}")
        return None


def _filter_to_qdrant(filter_: dict[str, Any] | None) -> qmodels.Filter | None:
    if not filter_:
        return None
    conditions: list[qmodels.FieldCondition] = []
    for key, val in filter_.items():
        conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=val)))
    return qmodels.Filter(must=conditions)


async def _search_collection(
    collection: str,
    query: str,
    *,
    k: int,
    min_score: float,
    filter_: dict[str, Any] | None,
) -> list[KBHit]:
    vec = await _embed(query)
    if vec is None:
        return []
    client = get_qdrant()
    try:
        result = await client.search(
            collection_name=collection,
            query_vector=vec,
            limit=k,
            query_filter=_filter_to_qdrant(filter_),
            with_payload=True,
        )
    except Exception as exc:  # noqa: BLE001 — Qdrant surfaces many error types
        logger.warning(f"Qdrant search on '{collection}' failed: {exc}")
        return []
    hits: list[KBHit] = []
    for point in result:
        if point.score < min_score:
            continue
        payload = dict(point.payload or {})
        text = payload.pop("text", "")
        hits.append(KBHit(text=text, score=float(point.score), metadata=payload))
    return hits


async def search(
    query: str, *, k: int = 5, filter: dict[str, Any] | None = None  # noqa: A002
) -> list[KBHit]:
    """RAG search over the ``kb`` collection."""
    return await _search_collection(
        KB_COLLECTION, query, k=k, min_score=MIN_SCORE_KB, filter_=filter
    )


async def search_news(
    query: str, *, k: int = 5, filter: dict[str, Any] | None = None  # noqa: A002
) -> list[KBHit]:
    """RAG search over the ``news`` collection."""
    return await _search_collection(
        NEWS_COLLECTION, query, k=k, min_score=MIN_SCORE_NEWS, filter_=filter
    )


def format_citations(hits: list[KBHit]) -> str:
    """Render a Markdown citation block — one bullet per hit."""
    if not hits:
        return "_No sources retrieved._"
    lines = ["**Sources:**"]
    for i, h in enumerate(hits, start=1):
        lines.append(f"{i}. {h.citation} _(score={h.score:.2f})_")
    return "\n".join(lines)


__all__ = [
    "KB_COLLECTION",
    "KBHit",
    "MIN_SCORE_KB",
    "MIN_SCORE_NEWS",
    "NEWS_COLLECTION",
    "format_citations",
    "get_qdrant",
    "search",
    "search_news",
]
