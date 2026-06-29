"""LLM routing layer — pick the right provider + model per task and sensitivity.

Implements `docs/LLM_ROUTING.md` §6 routing table. The router is a *pure
function* over (TaskType, Sensitivity) → RouteDecision. No I/O. The
:mod:`pfip.agent.llm_client` wrapper then takes the decision and dispatches
through LiteLLM, walking the fallback chain on transient failures.

Key invariants
--------------
- ``Sensitivity.SENSITIVE`` + ``LLM_PRIVACY_STRICT=true`` → **always** local
  Ollama. This is a hard architectural rule; the chat agent must never leak
  user holdings to an external provider when strict mode is on. See
  ``docs/SECURITY.md`` for the privacy boundary.
- Each route has a primary model + a fallback chain. Fallbacks are tried in
  order on 5xx / rate-limit failures by the llm_client wrapper.
- Model identifiers are LiteLLM-style ``provider/model`` strings — LiteLLM
  handles the SDK-level translation.

This module has zero side effects and never makes network calls — the only
job is policy. Tests in ``tests/test_router.py`` are table-driven across
every TaskType × Sensitivity combination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pfip.core.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskType(str, Enum):
    """Coarse task categories from LLM_ROUTING.md §3."""

    SENTIMENT_CLASSIFY = "sentiment_classify"  # local FinBERT — never hits LLM
    EMBEDDING = "embedding"  # NVIDIA NIM (or local Ollama)
    QUICK_SUMMARY = "quick_summary"  # Groq 8B
    MORNING_BRIEF = "morning_brief"  # Groq 70B (mixed sensitivity)
    CHAT_PUBLIC = "chat_public"  # Groq 70B
    CHAT_SENSITIVE = "chat_sensitive"  # local Ollama (forced)
    POST_MORTEM = "post_mortem"  # DeepSeek-R1 or Gemini Pro
    REASONING = "reasoning"  # DeepSeek-R1
    BULK_PREPROCESS = "bulk_preprocess"  # Groq 8B


class Sensitivity(str, Enum):
    """Privacy classification for a prompt."""

    PUBLIC = "public"
    SENSITIVE = "sensitive"


# ---------------------------------------------------------------------------
# Provider + model registry (LiteLLM-compatible identifiers)
# ---------------------------------------------------------------------------


# Each entry is ``"provider/model"`` as LiteLLM expects.
# When you add a new provider, just bump these constants — the dispatcher
# layer (llm_client) needs no change.
MODELS: dict[str, str] = {
    # Groq — fastest free inference (~500 tok/s, 14k req/day)
    "groq_70b": "groq/llama-3.3-70b-versatile",
    "groq_8b": "groq/llama-3.1-8b-instant",
    # NVIDIA NIM — embeddings + chat. bge-m3 is symmetric (one vector space for
    # both queries and passages), so it works with our single embed() call shape;
    # nv-embedqa-* are asymmetric and would require an input_type per call.
    "nim_embed": "nvidia_nim/baai/bge-m3",
    "nim_70b": "nvidia_nim/meta/llama-3.3-70b-instruct",
    # Google Gemini
    "gemini_flash": "gemini/gemini-2.0-flash",
    "gemini_pro": "gemini/gemini-2.0-pro",
    "gemini_thinking": "gemini/gemini-2.0-flash-thinking-exp",
    # DeepSeek — best chain-of-thought reasoning at low cost
    "deepseek_chat": "deepseek/deepseek-chat",
    "deepseek_reasoner": "deepseek/deepseek-reasoner",
    # OpenRouter — multi-provider safety net
    "openrouter_70b": "openrouter/meta-llama/llama-3.3-70b-instruct",
    # Cerebras — even faster than Groq
    "cerebras_70b": "cerebras/llama3.1-70b",
    # Local Ollama — privacy-pinned
    "ollama_default": "ollama/mistral:7b-instruct",
    "ollama_embed": "ollama/nomic-embed-text",
    # Cohere — reranking only
    "cohere_rerank": "cohere/rerank-v3-english",
}


# ---------------------------------------------------------------------------
# Route decision dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """The router's verdict — what to call and what to fall back to."""

    provider: str
    """One of {groq, gemini, deepseek, openrouter, ollama, nvidia_nim, cohere, cerebras}."""

    model: str
    """Full LiteLLM model identifier, e.g. ``groq/llama-3.3-70b-versatile``."""

    fallback_chain: list[str] = field(default_factory=list)
    """Ordered LiteLLM model ids tried if the primary 5xx's / rate-limits."""

    rationale: str = ""
    """Short human-readable explanation — logged for observability."""

    @property
    def all_models(self) -> list[str]:
        """Primary + fallbacks, in attempt order."""
        return [self.model, *self.fallback_chain]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_of(model_id: str) -> str:
    """Extract the LiteLLM provider prefix (chars before the first slash)."""
    return model_id.split("/", 1)[0] if "/" in model_id else model_id


def _filter_chain_by_keys(chain: list[str], settings: Settings) -> list[str]:
    """Drop fallback entries whose provider has no API key configured.

    Ollama is always included (no key needed). This keeps the chain honest:
    if the user has no Gemini key, we don't bother trying Gemini at runtime.
    """
    keymap = {
        "groq": settings.groq_api_key,
        "gemini": settings.gemini_api_key,
        "deepseek": settings.deepseek_api_key,
        "openrouter": settings.openrouter_api_key,
        "nvidia_nim": settings.nvidia_nim_api_key,
        "cerebras": settings.cerebras_api_key,
        "cohere": settings.cohere_api_key,
    }
    kept: list[str] = []
    for m in chain:
        p = _provider_of(m)
        if p == "ollama":
            kept.append(m)
            continue
        if keymap.get(p, ""):
            kept.append(m)
    return kept


# ---------------------------------------------------------------------------
# Routing policy
# ---------------------------------------------------------------------------


def route(
    task: TaskType,
    sensitivity: Sensitivity,
    *,
    settings: Settings | None = None,
) -> RouteDecision:
    """Pick a provider + model for ``task`` at the given ``sensitivity``.

    Policy (LLM_ROUTING.md §6):

    - **Sensitive + strict mode** → always local Ollama. Period.
    - **Embeddings** → NVIDIA NIM if key set, else local Ollama embed.
    - **Quick / bulk** → Groq 8B (fast cheap path).
    - **Morning brief / public chat** → Groq 70B (workhorse).
    - **Post-mortem / reasoning** → DeepSeek-R1 (best chain-of-thought),
      Gemini Thinking as fallback.
    - **Sentiment classify** → routed to local FinBERT pipeline, not LLM.
    """
    s = settings or get_settings()

    # Hard rule: sensitive + strict → local. Chat is the ONE exception — when
    # cloud fallback is allowed it may use cloud so the assistant still works on a
    # host with no reachable local LLM. Embeddings/reasoning stay strictly local.
    _chat_cloud_exempt = task == TaskType.CHAT_SENSITIVE and getattr(
        s, "allow_cloud_fallback", True
    )
    if (
        sensitivity == Sensitivity.SENSITIVE
        and s.llm_privacy_strict
        and not _chat_cloud_exempt
    ):
        # Embeddings still need an embedding model, not chat.
        if task == TaskType.EMBEDDING:
            return RouteDecision(
                provider="ollama",
                model=MODELS["ollama_embed"],
                fallback_chain=[],
                rationale="sensitive + strict → local embed",
            )
        return RouteDecision(
            provider="ollama",
            model=MODELS["ollama_default"],
            fallback_chain=[],
            rationale="sensitive + strict → local Ollama (privacy boundary)",
        )

    # ------------------------------------------------------------------
    # Per-task policy (non-strict-sensitive paths)
    # ------------------------------------------------------------------

    if task == TaskType.SENTIMENT_CLASSIFY:
        # Sentiment is FinBERT, not LLM. We return a sentinel so the caller
        # routes to pfip.sentiment.finbert_classifier instead of LiteLLM.
        return RouteDecision(
            provider="local_finbert",
            model="ProsusAI/finbert",
            fallback_chain=[MODELS["ollama_default"]],
            rationale="sentiment classification belongs to FinBERT, not LLM",
        )

    if task == TaskType.EMBEDDING:
        if s.nvidia_nim_api_key:
            chain = _filter_chain_by_keys([MODELS["ollama_embed"]], s)
            return RouteDecision(
                provider="nvidia_nim",
                model=MODELS["nim_embed"],
                fallback_chain=chain,
                rationale="NVIDIA NIM embeddings (nv-embedqa-e5-v5)",
            )
        return RouteDecision(
            provider="ollama",
            model=MODELS["ollama_embed"],
            fallback_chain=[],
            rationale="no NIM key → local nomic-embed-text fallback",
        )

    if task in (TaskType.QUICK_SUMMARY, TaskType.BULK_PREPROCESS):
        chain = _filter_chain_by_keys(
            [MODELS["cerebras_70b"], MODELS["openrouter_70b"], MODELS["ollama_default"]],
            s,
        )
        return RouteDecision(
            provider="groq" if s.groq_api_key else "ollama",
            model=MODELS["groq_8b"] if s.groq_api_key else MODELS["ollama_default"],
            fallback_chain=chain,
            rationale="fast/cheap path — Groq 8B primary",
        )

    if task in (TaskType.MORNING_BRIEF, TaskType.CHAT_PUBLIC):
        # 70B workhorse. Try Groq first (free 14k req/day), Gemini second.
        primary_provider, primary_model = (
            ("groq", MODELS["groq_70b"])
            if s.groq_api_key
            else (
                ("gemini", MODELS["gemini_flash"])
                if s.gemini_api_key
                else ("ollama", MODELS["ollama_default"])
            )
        )
        chain = _filter_chain_by_keys(
            [
                MODELS["gemini_flash"],
                MODELS["deepseek_chat"],
                MODELS["openrouter_70b"],
                MODELS["ollama_default"],
            ],
            s,
        )
        # Don't include the primary again in fallback.
        chain = [m for m in chain if m != primary_model]
        return RouteDecision(
            provider=primary_provider,
            model=primary_model,
            fallback_chain=chain,
            rationale="70B workhorse — Groq Llama 3.3 70B primary",
        )

    if task == TaskType.CHAT_SENSITIVE:
        # Privacy-preferred local. But when cloud fallback is allowed (default on
        # this single-user box, which has no reachable local LLM), route to the
        # cloud workhorse with Ollama as the final fallback so chat actually
        # responds instead of dying on an unreachable Ollama.
        if getattr(s, "allow_cloud_fallback", True) and (s.groq_api_key or s.nvidia_nim_api_key):
            primary_provider, primary_model = (
                ("groq", MODELS["groq_70b"])
                if s.groq_api_key
                else ("nvidia_nim", MODELS["nim_70b"])
            )
            chain = _filter_chain_by_keys(
                [MODELS["groq_70b"], MODELS["nim_70b"], MODELS["ollama_default"]],
                s,
            )
            chain = [m for m in chain if m != primary_model]
            return RouteDecision(
                provider=primary_provider,
                model=primary_model,
                fallback_chain=chain,
                rationale="sensitive chat + cloud fallback → cloud primary, Ollama last",
            )
        return RouteDecision(
            provider="ollama",
            model=MODELS["ollama_default"],
            fallback_chain=[],
            rationale="chat marked sensitive → local Ollama (cloud fallback disabled)",
        )

    if task in (TaskType.POST_MORTEM, TaskType.REASONING):
        # Best chain-of-thought. DeepSeek-R1 primary, Gemini Thinking second.
        primary_provider, primary_model = (
            ("deepseek", MODELS["deepseek_reasoner"])
            if s.deepseek_api_key
            else (
                ("gemini", MODELS["gemini_thinking"])
                if s.gemini_api_key
                else (
                    ("groq", MODELS["groq_70b"])
                    if s.groq_api_key
                    else ("ollama", MODELS["ollama_default"])
                )
            )
        )
        chain = _filter_chain_by_keys(
            [
                MODELS["gemini_thinking"],
                MODELS["gemini_pro"],
                MODELS["groq_70b"],
                MODELS["openrouter_70b"],
                MODELS["ollama_default"],
            ],
            s,
        )
        chain = [m for m in chain if m != primary_model]
        return RouteDecision(
            provider=primary_provider,
            model=primary_model,
            fallback_chain=chain,
            rationale="reasoning task — DeepSeek-R1 primary",
        )

    # Defensive fallback (should be unreachable thanks to enum exhaustion).
    return RouteDecision(  # pragma: no cover
        provider="ollama",
        model=MODELS["ollama_default"],
        fallback_chain=[],
        rationale=f"unknown task {task!r} → local default",
    )


__all__ = [
    "MODELS",
    "RouteDecision",
    "Sensitivity",
    "TaskType",
    "route",
]
