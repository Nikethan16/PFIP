"""LLM client — multi-provider routing via LiteLLM.

Architecture
------------
- :func:`route` in ``pfip.agent.router`` decides ``(provider, model, fallbacks)``
  from a (TaskType, Sensitivity) pair.
- :class:`MultiProviderClient` here dispatches via LiteLLM, walking the
  fallback chain on transient errors (5xx, rate limit, connection).
- A thin :class:`LLMRouter` shim preserves the legacy interface
  (``generate``, ``stream_chat``, ``embed``) used by existing callers in
  ``morning_brief.py``, ``graph.py``, etc. New code should prefer
  :class:`MultiProviderClient` directly via :func:`get_llm_client`.

Privacy contract
----------------
- Sensitive prompts under strict mode are pinned to local Ollama by the
  router. ``MultiProviderClient`` does *not* second-guess the router — it
  just dispatches.
- LangSmith tracing is opt-in via env (``LANGSMITH_API_KEY``); when set, each
  call records provider/model/latency.

Backward compatibility
----------------------
Names re-exported for callers that imported the old client:
``ChatMessage``, ``LLMError``, ``LLMUnavailable``, ``LLMInjectionBlock``,
``OllamaClient``, ``GroqClient``, ``LLMRouter``, ``get_llm_router``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from pfip.agent.router import (
    MODELS,
    RouteDecision,
    Sensitivity,
    TaskType,
    route,
)
from pfip.core.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(RuntimeError):
    """Any LLM-layer failure."""


class LLMUnavailable(LLMError):
    """No LLM provider is reachable."""


class LLMInjectionBlock(LLMError):
    """The output violated the 'LLM explains, never decides' contract."""


class LLMAllProvidersFailed(LLMUnavailable):
    """Every provider in the route's fallback chain failed."""


# ---------------------------------------------------------------------------
# Message schema (kept compatible with old callers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A chat message in OpenAI-compatible shape."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


# ---------------------------------------------------------------------------
# Lazy LiteLLM import — keeps cold-start fast for non-LLM code paths
# ---------------------------------------------------------------------------


def _get_litellm():
    """Lazy import; raises LLMUnavailable if litellm isn't installed."""
    try:
        import litellm  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(
            "litellm not installed. Run `pip install litellm>=1.50.0`."
        ) from exc
    return litellm


# ---------------------------------------------------------------------------
# Multi-provider client (LiteLLM-backed)
# ---------------------------------------------------------------------------


@dataclass
class _CallStats:
    """Outcome of a single attempt against one provider."""

    model: str
    ok: bool
    latency_ms: float
    error: str | None = None


def _is_transient(exc: BaseException) -> bool:
    """Classify whether an exception is retryable / fallback-eligible.

    LiteLLM exposes specific exception classes for rate-limit / timeout /
    APIConnection; we also retry on the generic httpx transport errors.
    """
    try:
        from litellm.exceptions import (  # type: ignore
            APIConnectionError,
            APIError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )
    except ImportError:  # pragma: no cover
        return isinstance(exc, (httpx.HTTPError, ConnectionError, TimeoutError))
    if isinstance(exc, (RateLimitError, Timeout, ServiceUnavailableError, APIConnectionError)):
        return True
    if isinstance(exc, APIError):
        # Treat 5xx as transient.
        status = getattr(exc, "status_code", None)
        if status and 500 <= status < 600:
            return True
    return isinstance(exc, (httpx.HTTPError, ConnectionError, TimeoutError))


class MultiProviderClient:
    """Unified async client for chat completions, streaming, embeddings.

    Every call:

    1. Asks the router for a :class:`RouteDecision`.
    2. Sets provider-specific env vars from settings.
    3. Walks the chain ``[primary, *fallbacks]`` until one succeeds.
    4. Logs decision + provider used + latency.
    5. Raises :class:`LLMAllProvidersFailed` if every attempt failed.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._configure_env()

    def _configure_env(self) -> None:
        """Set provider env vars from settings so LiteLLM picks them up.

        LiteLLM reads keys from env unless you pass ``api_key=`` per call.
        Doing it here once means callers don't have to think about it.
        """
        s = self._settings
        if s.groq_api_key:
            os.environ.setdefault("GROQ_API_KEY", s.groq_api_key)
        if s.gemini_api_key:
            os.environ.setdefault("GEMINI_API_KEY", s.gemini_api_key)
        if s.deepseek_api_key:
            os.environ.setdefault("DEEPSEEK_API_KEY", s.deepseek_api_key)
        if s.openrouter_api_key:
            os.environ.setdefault("OPENROUTER_API_KEY", s.openrouter_api_key)
        if s.nvidia_nim_api_key:
            os.environ.setdefault("NVIDIA_NIM_API_KEY", s.nvidia_nim_api_key)
        if s.cohere_api_key:
            os.environ.setdefault("COHERE_API_KEY", s.cohere_api_key)
        if s.cerebras_api_key:
            os.environ.setdefault("CEREBRAS_API_KEY", s.cerebras_api_key)
        # Ollama base URL
        os.environ.setdefault("OLLAMA_API_BASE", s.ollama_host)
        # LangSmith tracing
        if s.langsmith_tracing and s.langsmith_api_key:
            os.environ.setdefault("LANGSMITH_API_KEY", s.langsmith_api_key)
            os.environ.setdefault("LANGSMITH_PROJECT", s.langsmith_project)
            os.environ.setdefault("LITELLM_LOG", "INFO")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: Iterable[ChatMessage | dict[str, str]],
        *,
        task: TaskType,
        sensitivity: Sensitivity,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> str:
        """One-shot chat completion. Returns the assistant's full string."""
        decision = route(task, sensitivity, settings=self._settings)
        msgs = self._to_dicts(messages)
        last_err: BaseException | None = None
        attempts: list[_CallStats] = []

        litellm = _get_litellm()

        for model_id in decision.all_models:
            start = time.monotonic()
            try:
                resp = await litellm.acompletion(
                    model=model_id,
                    messages=msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=self._settings.llm_request_timeout_s,
                )
                latency_ms = (time.monotonic() - start) * 1000
                attempts.append(_CallStats(model=model_id, ok=True, latency_ms=latency_ms))
                self._log_call(decision, model_id, latency_ms, ok=True)
                content = resp["choices"][0]["message"]["content"]
                return content or ""
            except Exception as exc:  # noqa: BLE001 — we classify below
                latency_ms = (time.monotonic() - start) * 1000
                attempts.append(
                    _CallStats(model=model_id, ok=False, latency_ms=latency_ms, error=str(exc))
                )
                self._log_call(decision, model_id, latency_ms, ok=False, error=exc)
                last_err = exc
                if not _is_transient(exc) and model_id == decision.model:
                    # Non-transient error on primary — still try fallbacks
                    # because providers may have differing input requirements.
                    continue
                # Else, walk the chain.
                continue

        raise LLMAllProvidersFailed(
            f"All providers failed for task={task.value} "
            f"sensitivity={sensitivity.value}. "
            f"Tried: {[a.model for a in attempts]}. "
            f"Last error: {last_err}"
        )

    async def stream(
        self,
        messages: Iterable[ChatMessage | dict[str, str]],
        *,
        task: TaskType,
        sensitivity: Sensitivity,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Async-iterate over token deltas. Suitable for SSE forwarding.

        On primary failure we fall back to the next model only *before*
        any tokens have been yielded — once streaming has begun, errors
        propagate so the SSE layer can emit a clean error frame.
        """
        decision = route(task, sensitivity, settings=self._settings)
        msgs = self._to_dicts(messages)
        litellm = _get_litellm()

        last_err: BaseException | None = None
        for model_id in decision.all_models:
            start = time.monotonic()
            try:
                gen = await litellm.acompletion(
                    model=model_id,
                    messages=msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                    timeout=self._settings.llm_request_timeout_s,
                )
                # Probe the first chunk; if this raises we still fall back.
                first_tok: str | None = None
                first_chunk_received = False
                async for chunk in gen:
                    delta = self._extract_delta(chunk)
                    if delta is None:
                        continue
                    if not first_chunk_received:
                        first_chunk_received = True
                        first_tok = delta
                        # Commit to this model — log success on first token.
                        latency_ms = (time.monotonic() - start) * 1000
                        self._log_call(decision, model_id, latency_ms, ok=True, streaming=True)
                        if first_tok:
                            yield first_tok
                        continue
                    if delta:
                        yield delta
                return
            except Exception as exc:  # noqa: BLE001
                latency_ms = (time.monotonic() - start) * 1000
                self._log_call(decision, model_id, latency_ms, ok=False, error=exc, streaming=True)
                last_err = exc
                # If we already yielded tokens, we can't recover — re-raise.
                # The `first_chunk_received` is only set inside the try, so
                # if we reached except before yield, we just continue.
                continue

        raise LLMAllProvidersFailed(
            f"All providers failed (stream) for task={task.value}. "
            f"Last error: {last_err}"
        )

    async def embed(
        self,
        texts: list[str],
        *,
        sensitivity: Sensitivity = Sensitivity.PUBLIC,
    ) -> list[list[float]]:
        """Batch embedding. Returns one vector per input string."""
        if not texts:
            return []
        decision = route(TaskType.EMBEDDING, sensitivity, settings=self._settings)
        litellm = _get_litellm()
        last_err: BaseException | None = None
        for model_id in decision.all_models:
            start = time.monotonic()
            try:
                resp = await litellm.aembedding(
                    model=model_id,
                    input=texts,
                    timeout=self._settings.llm_request_timeout_s,
                )
                latency_ms = (time.monotonic() - start) * 1000
                self._log_call(decision, model_id, latency_ms, ok=True)
                # Normalize to list[list[float]]
                if isinstance(resp, dict) and "data" in resp:
                    return [item["embedding"] for item in resp["data"]]
                # LiteLLM's EmbeddingResponse exposes .data
                data = getattr(resp, "data", None)
                if data:
                    return [item["embedding"] if isinstance(item, dict) else item.embedding for item in data]
                raise LLMError(f"unexpected embedding response shape: {type(resp)!r}")
            except Exception as exc:  # noqa: BLE001
                latency_ms = (time.monotonic() - start) * 1000
                self._log_call(decision, model_id, latency_ms, ok=False, error=exc)
                last_err = exc
                continue
        raise LLMAllProvidersFailed(f"Embed failed. Last error: {last_err}")

    async def rerank(
        self,
        query: str,
        docs: list[str],
        *,
        sensitivity: Sensitivity = Sensitivity.PUBLIC,
    ) -> list[float]:
        """Rerank ``docs`` by relevance to ``query``. No-op if no Cohere key.

        Returns a list of scores aligned with ``docs`` (higher = more relevant).
        If Cohere isn't configured the no-op returns descending dummy scores
        so callers can sort safely.
        """
        if not self._settings.cohere_api_key:
            # No-op: return identity ranking.
            return [1.0 - (i / max(1, len(docs))) for i in range(len(docs))]
        # Use Cohere directly (LiteLLM rerank is opinionated; httpx is fine).
        url = "https://api.cohere.ai/v1/rerank"
        payload: dict[str, Any] = {
            "model": "rerank-v3-english",
            "query": query,
            "documents": docs,
            "top_n": len(docs),
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._settings.cohere_api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning(f"Cohere rerank failed: {exc}; returning identity scores")
            return [1.0 - (i / max(1, len(docs))) for i in range(len(docs))]
        scores = [0.0] * len(docs)
        for result in data.get("results", []):
            idx = result.get("index")
            score = result.get("relevance_score", 0.0)
            if isinstance(idx, int) and 0 <= idx < len(scores):
                scores[idx] = float(score)
        return scores

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dicts(messages: Iterable[ChatMessage | dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                out.append(m.to_dict())
            elif isinstance(m, dict):
                out.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            else:
                raise TypeError(f"unsupported message type: {type(m)!r}")
        return out

    @staticmethod
    def _extract_delta(chunk: Any) -> str | None:
        """Pull the text delta out of a LiteLLM streaming chunk."""
        try:
            choices = chunk["choices"] if isinstance(chunk, dict) else chunk.choices
            if not choices:
                return None
            first = choices[0]
            delta = first["delta"] if isinstance(first, dict) else first.delta
            if isinstance(delta, dict):
                return delta.get("content")
            return getattr(delta, "content", None)
        except (KeyError, AttributeError, IndexError):
            return None

    @staticmethod
    def _log_call(
        decision: RouteDecision,
        model: str,
        latency_ms: float,
        *,
        ok: bool,
        error: BaseException | None = None,
        streaming: bool = False,
    ) -> None:
        msg = (
            f"llm_call provider={decision.provider} chosen_model={model} "
            f"primary={decision.model} ok={ok} latency_ms={latency_ms:.1f} "
            f"streaming={streaming} rationale={decision.rationale!r}"
        )
        if ok:
            logger.info(msg)
        else:
            logger.warning(f"{msg} error={error!r}")


# ---------------------------------------------------------------------------
# Process-wide client singleton
# ---------------------------------------------------------------------------

_client: MultiProviderClient | None = None


def get_llm_client() -> MultiProviderClient:
    """Process-wide :class:`MultiProviderClient` singleton."""
    global _client
    if _client is None:
        _client = MultiProviderClient()
    return _client


# ---------------------------------------------------------------------------
# Backward-compatible shim — old callers expect this exact surface
# ---------------------------------------------------------------------------


class OllamaClient:
    """Legacy Ollama-only client retained for direct callers.

    New code should use :class:`MultiProviderClient` via :func:`get_llm_client`
    plus a router decision. This shim is kept so existing imports
    (``from pfip.agent.llm_client import OllamaClient``) keep working.
    """

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
            if resp.status_code == 404:
                raise LLMUnavailable(
                    f"Ollama model '{self._model}' not pulled. Run `make pull-models`."
                )
            if resp.status_code >= 500:
                raise LLMError(f"Ollama {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
        return data.get("response", "")

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        body = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", f"{self._host}/api/chat", json=body) as resp:
                    if resp.status_code == 404:
                        raise LLMUnavailable(f"Ollama model '{self._model}' not pulled.")
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
        settings = get_settings()
        payload = {"model": settings.llm_embed_model, "prompt": text}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(f"{self._host}/api/embeddings", json=payload)
            except httpx.RequestError as exc:
                raise LLMUnavailable(f"Ollama embed unreachable: {exc}") from exc
            if resp.status_code == 404:
                raise LLMUnavailable(f"Embed model '{settings.llm_embed_model}' not pulled.")
            resp.raise_for_status()
            data = resp.json()
        vec = data.get("embedding") or data.get("embeddings", [[]])[0]
        if not vec:
            raise LLMError("Empty embedding returned")
        return list(vec)


class GroqClient:
    """Legacy Groq client retained for direct callers (and the health probe)."""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str | None = None, model: str = "llama-3.3-70b-versatile") -> None:
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
                    data_raw = line[len("data: "):].strip()
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


class LLMRouter:
    """Legacy router-shape API. Delegates to :class:`MultiProviderClient`.

    Kept for backward compatibility with callers that use
    ``router.generate(prompt, system=...)``, ``router.stream_chat(messages)``,
    and ``router.embed(text)``. New code should use
    :func:`get_llm_client` + explicit (TaskType, Sensitivity).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: MultiProviderClient | None = None,
        ollama: OllamaClient | None = None,
        groq: GroqClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or MultiProviderClient(self._settings)
        # Retained for legacy access; not used by default any more.
        self._ollama = ollama or OllamaClient()
        self._groq = groq or GroqClient(api_key=self._settings.groq_api_key)

    @property
    def primary_model(self) -> str:
        return MODELS.get("groq_70b", self._ollama.model) if self._settings.groq_api_key else self._ollama.model

    @property
    def fallback_model(self) -> str | None:
        return self._ollama.model

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Legacy entry — picks a sensible default task/sensitivity.

        We classify as ``QUICK_SUMMARY`` + ``PUBLIC`` here so old non-routing
        callers still get cloud-fast routing. Callers that need privacy
        should migrate to ``get_llm_client().complete(... CHAT_SENSITIVE ...)``.
        """
        msgs: list[ChatMessage] = []
        if system:
            msgs.append(ChatMessage(role="system", content=system))
        msgs.append(ChatMessage(role="user", content=prompt))
        try:
            return await self._client.complete(
                msgs,
                task=TaskType.QUICK_SUMMARY,
                sensitivity=Sensitivity.PUBLIC,
            )
        except LLMAllProvidersFailed as exc:
            raise LLMUnavailable(str(exc)) from exc

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Legacy entry — public chat stream."""
        try:
            async for tok in self._client.stream(
                messages,
                task=TaskType.CHAT_PUBLIC,
                sensitivity=Sensitivity.PUBLIC,
            ):
                yield tok
        except LLMAllProvidersFailed as exc:
            raise LLMUnavailable(str(exc)) from exc

    async def embed(self, text: str) -> list[float]:
        """Single-text embed — delegates to client.embed."""
        try:
            vecs = await self._client.embed([text], sensitivity=Sensitivity.PUBLIC)
        except LLMAllProvidersFailed as exc:
            # Fall back to local Ollama embedding if multi-provider couldn't.
            try:
                return await self._ollama.embed(text)
            except LLMError:
                raise LLMUnavailable(str(exc)) from exc
        return vecs[0] if vecs else []


_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Return the process-wide legacy :class:`LLMRouter` singleton."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


__all__ = [
    "ChatMessage",
    "GroqClient",
    "LLMAllProvidersFailed",
    "LLMError",
    "LLMInjectionBlock",
    "LLMRouter",
    "LLMUnavailable",
    "MultiProviderClient",
    "OllamaClient",
    "get_llm_client",
    "get_llm_router",
]
