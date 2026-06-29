"""Fallback-chain behaviour of :class:`MultiProviderClient`.

We mock ``litellm.acompletion`` to simulate provider failures and verify the
client walks the chain until one succeeds. Also verifies that
:class:`LLMAllProvidersFailed` is raised when every attempt fails.
"""

from __future__ import annotations

from typing import Any

import pytest

# These tests exercise the litellm-backed MultiProviderClient. litellm is an
# optional/heavy dep; skip the whole module (rather than hard-fail) when it
# isn't installed, so the suite is green in any environment.
pytest.importorskip("litellm")

from pfip.agent.llm_client import (  # noqa: E402
    ChatMessage,
    LLMAllProvidersFailed,
    MultiProviderClient,
)
from pfip.agent.router import Sensitivity, TaskType
from pfip.core.config import Settings


class _FakeResponse(dict):
    """Mimic litellm's response dict shape just enough for our code."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self["choices"] = [{"message": {"content": content}}]


def _settings(**kwargs) -> Settings:  # type: ignore[no-untyped-def]
    """Build a Settings with overrides applied via alias names."""
    alias_map = {
        "groq_api_key": "GROQ_API_KEY",
        "nvidia_nim_api_key": "NVIDIA_NIM_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "cohere_api_key": "COHERE_API_KEY",
        "cerebras_api_key": "CEREBRAS_API_KEY",
        "llm_privacy_strict": "LLM_PRIVACY_STRICT",
        "allow_cloud_fallback": "ALLOW_CLOUD_FALLBACK",
    }
    base = {
        "GROQ_API_KEY": "g",
        "GEMINI_API_KEY": "x",
        "DEEPSEEK_API_KEY": "d",
        "OPENROUTER_API_KEY": "or",
        "NVIDIA_NIM_API_KEY": "",
        "COHERE_API_KEY": "",
        "CEREBRAS_API_KEY": "",
        "LLM_PRIVACY_STRICT": False,
        "ALLOW_CLOUD_FALLBACK": True,
    }
    for k, v in kwargs.items():
        base[alias_map.get(k, k)] = v
    return Settings(**base)


@pytest.mark.asyncio
async def test_complete_returns_first_success(monkeypatch) -> None:
    """First provider succeeds → returns its response, no fallback called."""
    s = _settings()
    client = MultiProviderClient(s)
    calls: list[str] = []

    async def fake_acompletion(*, model: str, messages: list, **_: Any) -> _FakeResponse:
        calls.append(model)
        return _FakeResponse(f"ok-from-{model}")

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await client.complete(
        [ChatMessage(role="user", content="hi")],
        task=TaskType.CHAT_PUBLIC,
        sensitivity=Sensitivity.PUBLIC,
    )
    assert "ok-from-" in result
    assert len(calls) == 1  # only primary was tried


@pytest.mark.asyncio
async def test_complete_walks_fallback_chain(monkeypatch) -> None:
    """Primary 5xx → second model is tried and succeeds."""
    s = _settings()
    client = MultiProviderClient(s)
    calls: list[str] = []

    from litellm.exceptions import ServiceUnavailableError  # type: ignore

    async def fake_acompletion(*, model: str, messages: list, **_: Any) -> _FakeResponse:
        calls.append(model)
        if len(calls) == 1:
            # Primary fails.
            raise ServiceUnavailableError(
                message="primary 503",
                llm_provider="groq",
                model=model,
            )
        return _FakeResponse(f"ok-from-{model}")

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await client.complete(
        [ChatMessage(role="user", content="hi")],
        task=TaskType.CHAT_PUBLIC,
        sensitivity=Sensitivity.PUBLIC,
    )
    assert "ok-from-" in result
    assert len(calls) >= 2  # primary + at least one fallback


@pytest.mark.asyncio
async def test_complete_raises_when_all_providers_fail(monkeypatch) -> None:
    """Every model errors → LLMAllProvidersFailed."""
    s = _settings()
    client = MultiProviderClient(s)

    from litellm.exceptions import ServiceUnavailableError  # type: ignore

    async def fake_acompletion(*, model: str, messages: list, **_: Any) -> _FakeResponse:
        raise ServiceUnavailableError(
            message="all-down",
            llm_provider="groq",
            model=model,
        )

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    with pytest.raises(LLMAllProvidersFailed):
        await client.complete(
            [ChatMessage(role="user", content="hi")],
            task=TaskType.CHAT_PUBLIC,
            sensitivity=Sensitivity.PUBLIC,
        )


@pytest.mark.asyncio
async def test_strict_sensitive_only_calls_ollama(monkeypatch) -> None:
    """Sensitive + strict + cloud fallback OFF → only ollama (privacy boundary).

    With ALLOW_CLOUD_FALLBACK=false the strict-local guarantee holds: sensitive
    chat never leaves the host. (When cloud fallback is on — the default — chat
    may use a cloud provider; see test_router.test_chat_sensitive_cloud_fallback.)
    """
    s = _settings(llm_privacy_strict=True, allow_cloud_fallback=False)
    client = MultiProviderClient(s)
    calls: list[str] = []

    async def fake_acompletion(*, model: str, messages: list, **_: Any) -> _FakeResponse:
        calls.append(model)
        return _FakeResponse("local-ok")

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    await client.complete(
        [ChatMessage(role="user", content="my portfolio question")],
        task=TaskType.CHAT_SENSITIVE,
        sensitivity=Sensitivity.SENSITIVE,
    )
    assert all(m.startswith("ollama/") for m in calls), calls
    assert len(calls) == 1  # no fallback under strict mode


@pytest.mark.asyncio
async def test_embed_uses_litellm_aembedding(monkeypatch) -> None:
    """Embedding path returns one vector per input string."""
    s = _settings(nvidia_nim_api_key="nim")
    client = MultiProviderClient(s)

    async def fake_aembedding(*, model: str, input: list, **_: Any) -> dict:  # noqa: A002
        return {"data": [{"embedding": [0.1, 0.2, 0.3]} for _ in input]}

    import litellm

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)

    vecs = await client.embed(["a", "b", "c"], sensitivity=Sensitivity.PUBLIC)
    assert len(vecs) == 3
    assert vecs[0] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_rerank_noop_when_no_cohere_key() -> None:
    """No Cohere key → identity ranking with descending dummy scores."""
    s = _settings()
    client = MultiProviderClient(s)
    scores = await client.rerank("query", ["a", "b", "c", "d"])
    assert len(scores) == 4
    # Strictly decreasing dummy ranking
    assert scores == sorted(scores, reverse=True)
