"""LLM client abstraction — Ollama primary, Groq fallback.

Design notes
------------
- The primary path hits **Ollama** at ``$OLLAMA_HOST`` (see ``core.config``)
  with ``$LLM_DEFAULT_MODEL`` (Mistral 7B by default).
- If Ollama returns a 5xx, a connection error, or times out, and
  ``GROQ_API_KEY`` is set, we automatically fall back to Groq's OpenAI-ish
  chat completions endpoint. Backoff is handled by ``tenacity``.
- ``stream_chat`` yields raw token strings as an async generator; the SSE
  layer converts those into ``event: token`` frames per CONTRACTS.md §7.
- If no model is available (Ollama down, no Groq key) we raise
  :class:`LLMUnavailable`. The API layer surfaces this as a helpful RFC-7807
  error telling the user to run ``make pull-models``.

We stay low-level (``httpx``) rather than depending on ``ollama-python`` to
keep cold-start fast and to expose the same streaming contract on both
providers.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential

from pfip.core.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(RuntimeError):
    """Any LLM-layer failure."""


class LLMUnavailable(LLMError):
    """No LLM provider is reachable. The caller should tell the user to run
    ``make pull-models`` or set ``GROQ_API_KEY``."""


class LLMInjectionBlock(LLMError):
    """The output violated the 'LLM explains, never decides' contract."""


# ---------------------------------------------------------------------------
# Message schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A chat message in OpenAI-compatible shape."""

    role: str  # "system" | "user" | "assistant"
    content: str


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------


class OllamaClient:
    """Thin async client for Ollama's HTTP API."""

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        settings = get_settings()
        self._host = (host or settings.ollama_host).rstrip("/")
        self._model = model or settings.llm_default_model
        self._timeout = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """One-shot completion."""
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(f"{self._host}/api/generate", json=payload)
            except httpx.RequestError as exc:
                raise LLMUnavailable(f"Ollama unreachable: {exc}") from exc
            if resp.status_code >= 500:
                raise LLMError(f"Ollama {resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 404:
                raise LLMUnavailable(
                    f"Ollama model '{self._model}' not pulled. "
                    "Run `make pull-models` or `ollama pull {model}`."
                )
            resp.raise_for_status()
            data = resp.json()
        return data.get("response", "")

    async def stream_chat(
        self, messages: list[ChatMessage]
    ) -> AsyncIterator[str]:
        """Stream tokens from ``/api/chat``.

        Yields each delta's ``message.content`` as it arrives. Raises
        :class:`LLMUnavailable` if the model is not pulled or Ollama is down.
        """
        body = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", f"{self._host}/api/chat", json=body
                ) as resp:
                    if resp.status_code == 404:
                        raise LLMUnavailable(
                            f"Ollama model '{self._model}' not pulled. "
                            "Run `make pull-models`."
                        )
                    if resp.status_code >= 500:
                        raise LLMError(f"Ollama {resp.status_code}")
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = chunk.get("message") or {}
                        tok = msg.get("content")
                        if tok:
                            yield tok
                        if chunk.get("done"):
                            return
        except httpx.RequestError as exc:
            raise LLMUnavailable(f"Ollama unreachable: {exc}") from exc

    async def embed(self, text: str) -> list[float]:
        """Compute an embedding via ``nomic-embed-text``."""
        settings = get_settings()
        payload = {"model": settings.llm_embed_model, "prompt": text}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(f"{self._host}/api/embeddings", json=payload)
            except httpx.RequestError as exc:
                raise LLMUnavailable(f"Ollama embed unreachable: {exc}") from exc
            if resp.status_code == 404:
                raise LLMUnavailable(
                    f"Embed model '{settings.llm_embed_model}' not pulled. "
                    "Run `make pull-models`."
                )
            resp.raise_for_status()
            data = resp.json()
        vec = data.get("embedding") or data.get("embeddings", [[]])[0]
        if not vec:
            raise LLMError("Empty embedding returned")
        return list(vec)


# ---------------------------------------------------------------------------
# Groq client (OpenAI-compatible API)
# ---------------------------------------------------------------------------


class GroqClient:
    """Groq free-tier fallback. Activated only if ``GROQ_API_KEY`` is set."""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str | None = None, model: str = "mixtral-8x7b-32768") -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._model = model

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        payload = {"model": self._model, "messages": msgs, "stream": False}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{self.BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_raw = line[len("data: ") :].strip()
                    if data_raw == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data_raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        delta = chunk["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError):
                        continue
                    if delta:
                        yield delta


# ---------------------------------------------------------------------------
# Router — Ollama first, Groq fallback
# ---------------------------------------------------------------------------


class LLMRouter:
    """Try Ollama; fall back to Groq on 5xx / timeout if configured."""

    def __init__(
        self,
        settings: Settings | None = None,
        ollama: OllamaClient | None = None,
        groq: GroqClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._ollama = ollama or OllamaClient()
        self._groq = groq or GroqClient()

    @property
    def primary_model(self) -> str:
        return self._ollama.model

    @property
    def fallback_model(self) -> str | None:
        return self._groq.model if self._groq.available else None

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """One-shot generate with Ollama→Groq fallback."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(2),
                wait=wait_exponential(multiplier=0.5, max=3.0),
                reraise=True,
            ):
                with attempt:
                    return await self._ollama.generate(prompt, system=system)
        except RetryError as exc:
            logger.warning(f"Ollama retry exhausted: {exc}")
        except LLMUnavailable as exc:
            logger.warning(f"Ollama unavailable: {exc}")
        except LLMError as exc:
            logger.warning(f"Ollama error, falling back: {exc}")

        if self._groq.available:
            logger.info("Falling back to Groq")
            return await self._groq.generate(prompt, system=system)
        raise LLMUnavailable(
            "No LLM backend reachable. Run `make pull-models` to pull Mistral "
            "locally, or set GROQ_API_KEY for cloud fallback."
        )

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Stream with fallback — yields tokens."""
        # First try Ollama. If the very first line fails, fall back to Groq.
        try:
            gen = self._ollama.stream_chat(messages)
            # Probe: grab first token; if it comes back we commit to Ollama.
            first = await gen.__anext__()
            yield first
            async for tok in gen:
                yield tok
            return
        except StopAsyncIteration:
            return
        except LLMUnavailable as exc:
            logger.warning(f"Ollama stream unavailable: {exc}")
        except (LLMError, httpx.HTTPError) as exc:
            logger.warning(f"Ollama stream error: {exc}")

        if self._groq.available:
            logger.info("Streaming via Groq fallback")
            async for tok in self._groq.stream_chat(messages):
                yield tok
            return
        raise LLMUnavailable(
            "No LLM backend reachable. Run `make pull-models` to pull Mistral "
            "locally, or set GROQ_API_KEY for cloud fallback."
        )

    async def embed(self, text: str) -> list[float]:
        """Embeddings are Ollama-only (we don't duplicate Groq embed paths)."""
        return await self._ollama.embed(text)


# Singleton accessor – cheap to instantiate but handy for DI.
_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Return the process-wide :class:`LLMRouter` singleton."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


__all__ = [
    "ChatMessage",
    "GroqClient",
    "LLMError",
    "LLMInjectionBlock",
    "LLMRouter",
    "LLMUnavailable",
    "OllamaClient",
    "get_llm_router",
]
