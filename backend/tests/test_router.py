"""Table-driven tests for :mod:`pfip.agent.router`.

Verifies the (TaskType, Sensitivity) → RouteDecision matrix from
``docs/LLM_ROUTING.md`` §6:

- Sensitive + strict → local Ollama (always).
- Embedding → NVIDIA NIM if key set, else local.
- Quick / bulk → Groq 8B.
- Morning brief / chat public → Groq 70B.
- Post-mortem / reasoning → DeepSeek-R1.
- Fallback chain drops providers without keys.
"""

from __future__ import annotations

import pytest

from pfip.agent.router import (
    MODELS,
    RouteDecision,
    Sensitivity,
    TaskType,
    route,
)
from pfip.core.config import Settings


def _settings(**kwargs) -> Settings:  # type: ignore[no-untyped-def]
    """Build a Settings instance with all relevant fields overridable.

    The Settings model uses upper-case ENV-style aliases (``GROQ_API_KEY``
    etc.); pydantic-settings only accepts those by alias, so we translate
    keyword args here.
    """
    alias_map = {
        "groq_api_key": "GROQ_API_KEY",
        "nvidia_nim_api_key": "NVIDIA_NIM_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "cohere_api_key": "COHERE_API_KEY",
        "cerebras_api_key": "CEREBRAS_API_KEY",
        "llm_privacy_strict": "LLM_PRIVACY_STRICT",
    }
    base = {
        "GROQ_API_KEY": "",
        "NVIDIA_NIM_API_KEY": "",
        "GEMINI_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "COHERE_API_KEY": "",
        "CEREBRAS_API_KEY": "",
        "LLM_PRIVACY_STRICT": True,
    }
    for k, v in kwargs.items():
        base[alias_map.get(k, k)] = v
    return Settings(**base)


# ---------------------------------------------------------------------------
# Strict mode: sensitive ALWAYS local
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task",
    [
        TaskType.MORNING_BRIEF,
        TaskType.CHAT_PUBLIC,
        TaskType.POST_MORTEM,
        TaskType.REASONING,
        TaskType.QUICK_SUMMARY,
        TaskType.BULK_PREPROCESS,
        TaskType.CHAT_SENSITIVE,
    ],
)
def test_sensitive_strict_forces_local(task: TaskType) -> None:
    """Any task + Sensitive + strict → ollama, no fallbacks."""
    s = _settings(groq_api_key="key", gemini_api_key="key", llm_privacy_strict=True)
    decision = route(task, Sensitivity.SENSITIVE, settings=s)
    assert decision.provider == "ollama"
    assert decision.model == MODELS["ollama_default"]
    assert decision.fallback_chain == []


def test_sensitive_embedding_strict_uses_local_embed() -> None:
    s = _settings(nvidia_nim_api_key="key", llm_privacy_strict=True)
    decision = route(TaskType.EMBEDDING, Sensitivity.SENSITIVE, settings=s)
    assert decision.provider == "ollama"
    assert decision.model == MODELS["ollama_embed"]


# ---------------------------------------------------------------------------
# Public routing
# ---------------------------------------------------------------------------


def test_embedding_public_prefers_nim_when_keyed() -> None:
    s = _settings(nvidia_nim_api_key="nim-key")
    decision = route(TaskType.EMBEDDING, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "nvidia_nim"
    assert decision.model == MODELS["nim_embed"]
    assert MODELS["ollama_embed"] in decision.fallback_chain


def test_embedding_public_falls_back_to_ollama_without_nim() -> None:
    s = _settings()
    decision = route(TaskType.EMBEDDING, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "ollama"
    assert decision.model == MODELS["ollama_embed"]


def test_quick_summary_uses_groq_8b_when_keyed() -> None:
    s = _settings(groq_api_key="g")
    decision = route(TaskType.QUICK_SUMMARY, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "groq"
    assert decision.model == MODELS["groq_8b"]


def test_quick_summary_no_key_defaults_local() -> None:
    s = _settings()
    decision = route(TaskType.QUICK_SUMMARY, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "ollama"
    assert decision.model == MODELS["ollama_default"]


def test_morning_brief_public_prefers_groq_70b() -> None:
    s = _settings(groq_api_key="g", gemini_api_key="x")
    decision = route(TaskType.MORNING_BRIEF, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "groq"
    assert decision.model == MODELS["groq_70b"]
    # Gemini in fallback chain
    assert MODELS["gemini_flash"] in decision.fallback_chain


def test_chat_public_prefers_groq_70b() -> None:
    s = _settings(groq_api_key="g")
    decision = route(TaskType.CHAT_PUBLIC, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "groq"
    assert decision.model == MODELS["groq_70b"]


def test_chat_sensitive_always_local_even_non_strict() -> None:
    s = _settings(groq_api_key="g", llm_privacy_strict=False)
    decision = route(TaskType.CHAT_SENSITIVE, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "ollama"
    assert decision.model == MODELS["ollama_default"]


def test_post_mortem_prefers_deepseek_when_keyed() -> None:
    s = _settings(deepseek_api_key="d", gemini_api_key="g")
    decision = route(TaskType.POST_MORTEM, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "deepseek"
    assert decision.model == MODELS["deepseek_reasoner"]


def test_post_mortem_falls_back_to_gemini_then_local() -> None:
    s = _settings(gemini_api_key="g")
    decision = route(TaskType.REASONING, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "gemini"
    assert decision.model == MODELS["gemini_thinking"]
    # Local Ollama should always be the last-resort tail.
    assert MODELS["ollama_default"] in decision.fallback_chain


def test_sentiment_classify_routes_to_finbert() -> None:
    s = _settings()
    decision = route(TaskType.SENTIMENT_CLASSIFY, Sensitivity.PUBLIC, settings=s)
    assert decision.provider == "local_finbert"


# ---------------------------------------------------------------------------
# Fallback-chain hygiene
# ---------------------------------------------------------------------------


def test_fallback_chain_drops_providers_without_keys() -> None:
    """With only Groq configured, fallbacks should be Ollama-only."""
    s = _settings(groq_api_key="g")
    decision = route(TaskType.MORNING_BRIEF, Sensitivity.PUBLIC, settings=s)
    # Gemini/DeepSeek/OpenRouter not configured, so chain == [ollama] (or
    # subset of those plus ollama). The point: no unconfigured provider
    # remains in the chain.
    for m in decision.fallback_chain:
        provider = m.split("/", 1)[0]
        assert provider in {"ollama"}, f"unconfigured provider leaked: {provider}"


def test_fallback_chain_contains_ollama_always() -> None:
    """Cloud routes always have local Ollama as ultimate fallback."""
    s = _settings(groq_api_key="g", gemini_api_key="x", deepseek_api_key="d")
    for task in (TaskType.MORNING_BRIEF, TaskType.CHAT_PUBLIC, TaskType.REASONING):
        decision = route(task, Sensitivity.PUBLIC, settings=s)
        assert (
            MODELS["ollama_default"] in decision.all_models
        ), f"task={task} missing local fallback: {decision.all_models}"


# ---------------------------------------------------------------------------
# RouteDecision shape
# ---------------------------------------------------------------------------


def test_route_decision_all_models_includes_primary_first() -> None:
    s = _settings(groq_api_key="g", gemini_api_key="x")
    decision = route(TaskType.MORNING_BRIEF, Sensitivity.PUBLIC, settings=s)
    assert decision.all_models[0] == decision.model
    assert isinstance(decision, RouteDecision)
    assert decision.rationale  # non-empty
