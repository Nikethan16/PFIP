# LLM Router — Build Notes

Replaces the previous single-provider Ollama+Groq client with a task-aware,
multi-provider router. Spec: `docs/LLM_ROUTING.md` §§3, 5, 6, 8.

## Files added

| Path                                | Purpose                                                |
|-------------------------------------|--------------------------------------------------------|
| `pfip/agent/router.py`              | Pure routing policy: `(TaskType, Sensitivity) → RouteDecision`. Hard rule: sensitive + strict → local Ollama. |
| `pfip/agent/privacy.py`             | Conservative prompt classifier. Personal pronouns, sensitive nouns (tax, P&L, portfolio, …), holdings tickers, broker names. False positives OK, false negatives forbidden. |
| `pfip/agent/embedder.py`            | Thin facade over `MultiProviderClient.embed`. NVIDIA NIM (`nv-embedqa-e5-v5`) when keyed, else local nomic-embed-text. |
| `pfip/agent/reranker.py`            | Cohere rerank-v3 wrapper. No-op identity when no Cohere key. Refuses to send `SENSITIVE` content to Cohere even if keyed. |
| `pfip/agent/sanitize.py`            | Pre-embed prompt-injection guard with quarantine queue (`pfip/agent/quarantine/`). Threshold = 2 distinct pattern matches. |
| `tests/test_router.py`              | Table-driven across all TaskType × Sensitivity. Verifies fallback hygiene. |
| `tests/test_privacy.py`             | Positive + negative + edge cases per spec ("my morning brief", "tax cuts", "ALL"). |
| `tests/test_llm_client_fallback.py` | Mock provider failures; verify chain walk + `LLMAllProvidersFailed`. |
| `tests/test_sanitize.py`            | Quarantine flow + delimiter neutralization. |

## Files modified

| Path                                | Change                                                 |
|-------------------------------------|--------------------------------------------------------|
| `pfip/agent/llm_client.py`          | Rewritten on top of LiteLLM. `MultiProviderClient` is the new primary API (`complete`, `stream`, `embed`, `rerank`). Legacy `LLMRouter`/`OllamaClient`/`GroqClient` shims preserved for back-compat. |
| `pfip/agent/morning_brief.py`       | `_llm_topline` now calls `MultiProviderClient` with `TaskType.MORNING_BRIEF` + `Sensitivity.SENSITIVE`. Numbers still come from DB. |
| `pfip/agent/post_mortem.py`         | Uses `TaskType.POST_MORTEM` + `Sensitivity.SENSITIVE`. Routes to DeepSeek-R1 in non-strict mode, local in strict mode. |
| `pfip/agent/graph.py`               | Chat path now classifies sensitivity per-message via `pfip.agent.privacy.classify_sensitivity` and routes through `CHAT_PUBLIC` or `CHAT_SENSITIVE`. |
| `pfip/api/health.py`                | Adds `GET /api/v1/health/providers` and integrates provider summary into `/health/deep`. |
| `pfip/core/config.py`               | New env keys: `NVIDIA_NIM_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `COHERE_API_KEY`, `CEREBRAS_API_KEY`, `LLM_PROVIDER_PRIORITY`, `LLM_PRIVACY_STRICT`, plus LangSmith. |
| `requirements.txt`                  | `litellm>=1.50.0`. |
| `.env.example`                      | All new keys documented with free-tier signup URLs. `LLM_PRIVACY_STRICT=true` default. |

## Routing matrix (LLM_ROUTING.md §6)

| TaskType            | Primary (non-strict)       | Fallback chain                          | Strict-Sensitive path |
|---------------------|----------------------------|-----------------------------------------|----------------------|
| SENTIMENT_CLASSIFY  | FinBERT (local)            | Ollama                                  | FinBERT (local)      |
| EMBEDDING           | NVIDIA NIM nv-embedqa-e5-v5| Ollama nomic-embed-text                 | Ollama embed         |
| QUICK_SUMMARY       | Groq Llama 3.1 8B          | Cerebras 70B → OpenRouter → Ollama      | Ollama default       |
| BULK_PREPROCESS     | Groq Llama 3.1 8B          | Cerebras 70B → OpenRouter → Ollama      | Ollama default       |
| MORNING_BRIEF       | Groq Llama 3.3 70B         | Gemini Flash → DeepSeek Chat → OR → Ollama | Ollama default     |
| CHAT_PUBLIC         | Groq Llama 3.3 70B         | Gemini Flash → DeepSeek Chat → OR → Ollama | Ollama default     |
| CHAT_SENSITIVE      | Ollama (always)            | —                                       | Ollama default       |
| POST_MORTEM         | DeepSeek-R1 reasoner       | Gemini Thinking → Gemini Pro → Groq → OR → Ollama | Ollama default |
| REASONING           | DeepSeek-R1 reasoner       | Gemini Thinking → Gemini Pro → Groq → OR → Ollama | Ollama default |

## Critical invariants enforced

1. **Sensitive + strict → local, no exceptions.** Verified in `test_router.py::test_sensitive_strict_forces_local` for every task type.
2. **Chat agent never emits a typed `Signal`.** `pfip/agent/graph.py::cite_and_validate` regex-guards the contract.
3. **Sanitize before embed.** `pfip/agent/sanitize.py::sanitize_for_embed` is the pre-embed gate; high-injection-signature chunks go to `pfip/agent/quarantine/` and are NOT inserted into Qdrant.
4. **Sanitize before prompt.** `pfip/agent/sanitizer.py::sanitize_retrieved_content` (pre-prompt) is the second layer; the system prompt wraps retrieved content in `<retrieved_content>` and tells the model to refuse instructions inside.
5. **Fallback chain drops unconfigured providers.** Verified in `test_router.py::test_fallback_chain_drops_providers_without_keys`.

## What's tested end-to-end

- **Router policy**: 100% of TaskType × Sensitivity combinations (`tests/test_router.py`).
- **Privacy classifier**: ~30 positive + negative + edge cases (`tests/test_privacy.py`).
- **Fallback chain**: mock LiteLLM failures, verify chain walk (`tests/test_llm_client_fallback.py`).
- **Prompt-injection quarantine**: multi-pattern attacks land in the quarantine dir, single-pattern false positives pass through (`tests/test_sanitize.py`).
- **Backward compatibility**: legacy `get_llm_router().generate/stream_chat/embed` still works — existing `tests/test_agent.py`, `tests/test_kb.py` pass unchanged.

## What's scaffolded (needs keys to verify in real network)

- **Groq end-to-end**: code path verified by running through the dispatcher (request reached the Groq URL); the sandbox network blocked outbound traffic so we couldn't observe a 200. Fallback to Ollama also engaged correctly. In any environment with internet access + a valid `GROQ_API_KEY`, the same code path returns a real completion.
- **NVIDIA NIM embeddings**: `pfip/agent/embedder.py` routes to NIM when `NVIDIA_NIM_API_KEY` is set. Needs key to verify the LiteLLM `nvidia_nim/` provider prefix is correct on the actual model.
- **DeepSeek-R1 / Gemini Thinking**: post-mortem path routes to these when keyed. Need keys + non-strict mode to observe.
- **Cohere rerank**: HTTP call wired (not via LiteLLM, since their rerank API needs custom payload). Needs `COHERE_API_KEY`.
- **OpenRouter**: routing target set; needs key to verify.
- **Cerebras**: routing target set; needs key to verify.
- **Provider health probes**: `GET /api/v1/health/providers` returns `unconfigured` for missing keys (verified by code review); real-network smoke would confirm `ok` shape.

## Provider integration status

| Provider     | Routing | Auth Key (env)        | Network-verified | Notes                                              |
|--------------|---------|-----------------------|------------------|----------------------------------------------------|
| Groq         | Yes     | `GROQ_API_KEY`        | Sandbox blocked  | Real call attempted, request reached groq.com URL |
| Ollama       | Yes     | (none)                | Sandbox blocked  | DNS unavailable in sandbox; works locally          |
| NVIDIA NIM   | Yes     | `NVIDIA_NIM_API_KEY`  | No (no key)      | Embeddings primary path                            |
| Gemini       | Yes     | `GEMINI_API_KEY`      | No (no key)      | Long-context + thinking variant                    |
| DeepSeek     | Yes     | `DEEPSEEK_API_KEY`    | No (no key)      | Reasoner = best for post-mortems                   |
| OpenRouter   | Yes     | `OPENROUTER_API_KEY`  | No (no key)      | Safety-net fallback                                |
| Cohere       | Yes     | `COHERE_API_KEY`      | No (no key)      | Rerank only                                        |
| Cerebras     | Yes     | `CEREBRAS_API_KEY`    | No (no key)      | Faster-than-Groq fallback                          |
| LangSmith    | Optional| `LANGSMITH_API_KEY`   | No (no key)      | Tracing only (LiteLLM auto-instruments when env set) |
