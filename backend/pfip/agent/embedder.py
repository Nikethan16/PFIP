"""Embedding interface used by KB ingest + news pipeline.

The router (``pfip.agent.router``) picks the embedding provider per the rule:
NVIDIA NIM ``nv-embedqa-e5-v5`` if ``NVIDIA_NIM_API_KEY`` is set, else local
Ollama ``nomic-embed-text``. This module exposes a single :class:`Embedder`
facade callers depend on without caring which it is.

Downstream code that previously did ``await get_llm_router().embed(text)``
should migrate to::

    from pfip.agent.embedder import get_embedder
    vecs = await get_embedder().embed(["chunk 1", "chunk 2"])

That single-text path keeps working — see :meth:`Embedder.embed_one`.
"""

from __future__ import annotations

from typing import Iterable

from loguru import logger

from pfip.agent.llm_client import LLMAllProvidersFailed, LLMUnavailable, get_llm_client
from pfip.agent.router import Sensitivity, TaskType, route
from pfip.core.config import Settings, get_settings


class Embedder:
    """Thin wrapper around ``MultiProviderClient.embed``.

    Public methods:
      - :meth:`embed` — batch (list[str] → list[list[float]]).
      - :meth:`embed_one` — single text → vector (legacy convenience).
      - :meth:`dim` — best-effort dimensionality of the active model.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = get_llm_client()
        self._cached_dim: int | None = None

    @property
    def active_model(self) -> str:
        """Return the model that would be used right now."""
        decision = route(TaskType.EMBEDDING, Sensitivity.PUBLIC, settings=self._settings)
        return decision.model

    async def embed(self, texts: Iterable[str]) -> list[list[float]]:
        """Embed a batch of strings."""
        texts_list = [t for t in texts if t]
        if not texts_list:
            return []
        try:
            vecs = await self._client.embed(texts_list, sensitivity=Sensitivity.PUBLIC)
        except LLMAllProvidersFailed as exc:
            raise LLMUnavailable(f"Embedding failed: {exc}") from exc
        if vecs and self._cached_dim is None:
            self._cached_dim = len(vecs[0])
        return vecs

    async def embed_one(self, text: str) -> list[float]:
        """Single-string embed — convenience used by legacy callers."""
        vecs = await self.embed([text])
        return vecs[0] if vecs else []

    async def dim(self) -> int | None:
        """Best-effort embedding dimension. Probes the model once if needed."""
        if self._cached_dim is not None:
            return self._cached_dim
        try:
            vec = await self.embed_one("probe")
        except LLMUnavailable as exc:
            logger.warning(f"dim probe failed: {exc}")
            return None
        return len(vec) if vec else None


# Singleton accessor
_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


__all__ = ["Embedder", "get_embedder"]
