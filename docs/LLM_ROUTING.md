# LLM Routing — what model for what task

How PFIP uses LLMs (and where it explicitly doesn't), how requests should be routed across providers, and the privacy boundary that constrains everything.

This doc is the input to the model registry + agent layer. Update it when use cases change.

---

## 1. What the platform actually does (capability map)

PFIP is a personal-scale aggregator + analyzer + advisor built around a daily/weekly decision rhythm. Six core capabilities:

| # | Capability | Description |
|---|---|---|
| 1 | **Data collection** | Continuous ingest of OHLCV, fundamentals, on-chain, derivatives, FX, macro, news, social across crypto + US + Indian markets. Storage in TimescaleDB + Qdrant. Prefect-scheduled. |
| 2 | **Signal generation** | ML models (LightGBM + HMM regime + ensembles) emit BUY/SELL/HOLD per asset with confidence scores. Walk-forward validated. **Zero LLM involvement by design.** |
| 3 | **Risk + portfolio** | Tracks holdings (CSV-imported). P&L, exposure, correlation, VaR, drawdown. Enforces position-size cap, drawdown halt, correlation guard. Pre-trade checklist required. Post-mortem mandatory on close. |
| 4 | **Indian tax engine** | Deterministic. STCG/LTCG with grandfathering. DTAA/Form 67. Schedule FA. 80C/D/CCD optimizer. **Never an LLM** — tax law has zero tolerance for hallucination. |
| 5 | **Knowledge synthesis** | Library of trading books ingested into vector DB. Retrievable by semantic search. Agent quotes with citations. |
| 6 | **Human interface** | Mobile-responsive Next.js dashboard (charts, portfolio, signals, tax, calibration, chat) + Telegram alerts. |

## 2. Daily workflow

```
05:00–07:00 IST  Overnight ingest (crypto hourly, equities EOD, news 15-min, features, regime, signals, calibration)
07:00 IST        Morning brief delivered (Telegram + dashboard home)
                 ├─ Overnight moves table
                 ├─ Today's economic calendar
                 ├─ Top 3 news per watchlist
                 ├─ Regime state per market
                 ├─ Watchlist deltas
                 ├─ Open-position risk snapshot
                 ├─ Calibration note
                 └─ Shadow vs actual delta
Throughout day   User opens dashboard, asks chat agent questions
                 If trade considered → fills pre-trade checklist (forced)
                 If trade taken → logged to journal
                 If position closed → post-mortem auto-drafted, user edits
17:30 IST        Market close summary
23:30 IST        Shadow portfolio reconcile
Sunday 19:00     Weekly review
First Sat/month  Calibration report + Tier-S/A/B review
First Sat/qtr    Restore-from-backup drill
April            ITR calibration run
```

## 3. Where LLMs fit — task-by-task

LLMs are useful where tasks need natural language understanding/generation, reasoning over text, plain-language explanation, or cross-source synthesis. They're NOT useful for deterministic math, structured DB ops, or anything where hallucination has cost.

### 3.1 LOW-complexity tasks (small/fast LLM is plenty)

| Task | Criticality | Required model | Privacy |
|---|---|---|---|
| News sentiment classification (per article) | Medium | **Not an LLM.** FinBERT (110M, CPU). | Public |
| News entity linking (which ticker, sector, person) | Medium | Small LLM with structured output (Llama 3.1 8B) OR specialized NER | Public |
| Quick news summarization (bulk overnight) | Low | Llama 3.1 8B on Groq | Public |
| Chat: factual lookups ("BTC last close?") | High (UX) | Should not go to LLM — DB query routed by intent classifier | Mixed |

### 3.2 MEDIUM-complexity tasks (mid-quality LLM matters)

| Task | Criticality | Required model | Privacy |
|---|---|---|---|
| **Morning brief generation** | **Critical** (daily touchpoint) | 70B-class: Llama 3.3 70B (Groq) or Gemini 2.0 Flash | Mixed (your portfolio appears) |
| Chat agent: "why did X move?" | High | Llama 3.3 70B or Gemini 2.0 Flash | Public |
| Chat agent: portfolio queries ("my IT exposure?") | High | 70B-class with tool-calling: Llama 3.3 70B | **Sensitive — your holdings** |
| Knowledge base RAG synthesis ("what would Lefèvre say?") | Medium-high | 70B-class. **Embedding model is the bigger lever** than chat LLM. | Public |
| Pre-trade checklist auto-fill | High | 70B-class | **Sensitive** — about your intended trade |
| Calibration commentary | Medium | 70B-class | Public-ish (model performance) |

### 3.3 HIGH-complexity tasks (frontier reasoning required)

| Task | Criticality | Required model | Privacy |
|---|---|---|---|
| **Post-mortem drafting** on closed positions | **Critical** (learning loop) | Reasoning model: DeepSeek-R1 or Gemini 2.0 Pro (Thinking mode) | **Sensitive** |
| Book → feature/rule translation (one-time bulk) | Medium | Frontier: DeepSeek-V3, Llama 3.3 70B, Gemini 2.0 Pro | Public |
| Numerical reasoning over filings (FinQA-style) | Low (validation) | Reasoning model: DeepSeek-R1 distilled or Gemini 2.0 Pro | Public |
| Weekly review synthesis (Sunday agent retro) | Medium | 70B-class enough; Gemini 2.0 Pro better | **Sensitive** |
| "Should I rebalance?" reasoning | High when invoked | Frontier + chain-of-thought: DeepSeek-R1 | **Sensitive** |

### 3.4 NEVER LLM — architecturally enforced

| Task | Why |
|---|---|
| Trade decision (BUY/SELL/HOLD) | LLM hallucinates. Use ML models with calibrated confidence + rules. |
| Tax calculations | Deterministic legal rules. Wrong answer = real money mistake. |
| Risk-rule enforcement | Hard rules. Position-size cap, drawdown halt, correlation guard — code, not language. |
| Backtest math | Walk-forward, CPCV, Monte Carlo are deterministic. |
| DB queries (when intent is structured) | Use intent router → SQL, not LLM-generated SQL. |
| Price prediction | Foundation models tie naive baselines on returns; LLMs are worse. |

## 4. Importance per capability

| Capability | LLM importance | If LLM is bad |
|---|---|---|
| Data collection | None | Nothing changes |
| Signal generation | None | Nothing changes (architectural rule) |
| Risk + portfolio | Low (only for explanation) | Numbers still right; just less readable |
| Tax engine | None (only for explanation) | Numbers still right |
| Knowledge synthesis | **High** | Citations get wrong, synthesis fluffy |
| Human interface (chat + brief + post-mortem) | **Critical** | Bad LLM = bad PFIP. This IS the user-facing product. |

LLM matters for ~30% of the platform's surface, but that 30% is what the user touches daily.

## 5. Privacy boundary

> Your portfolio holdings + tax data are sensitive. Holding-related prompts go to local Ollama. Public-market prompts go to cloud.

The agent auto-routes based on whether the prompt references your portfolio. Implementation: a routing layer that scans the prompt for portfolio identifiers (symbols you own, "my", "I", account names) before deciding which backend to call.

If a prompt is **public** (e.g., "summarize today's BTC news"), cloud LLM is fine.
If a prompt is **sensitive** (e.g., "given my exposure, should I rebalance?"), local LLM only.

### Privacy hardening (2026-06-04 audit)

The classifier is no longer the only line of defence. Two changes make the holdings boundary
structural rather than best-effort:

1. **Holdings symbols are fed to the classifier.** `backend/pfip/agent/graph.py` passes the
   user's *open-holding symbols* into the privacy classifier, so a prompt that names a symbol
   the user actually owns is recognised as sensitive even if it lacks pronouns or the word
   "portfolio".
2. **Structural SENSITIVE forcing.** Whenever any holding row was retrieved into the prompt,
   the agent **forces** `SENSITIVE` regardless of what the classifier returned — so holdings
   can never route to a cloud LLM even on a classifier miss. The streaming call was switched
   to the sensitivity-routing `MultiProviderClient.stream`.

Net effect: holdings never leave the machine via a cloud provider. A false negative from the
text classifier no longer leaks data, because the presence of holding rows in the prompt
overrides it.

## 6. Provider routing (recommended)

| Layer | Provider | Why |
|---|---|---|
| Sentiment classifiers (FinBERT, CryptoBERT) | Local, CPU | Specialized small models. Don't waste API calls. |
| Embeddings (KB + news) | **NVIDIA NIM** (NV-Embed-v2 / nv-embedqa-e5-v5), free | Quality > local nomic-embed-text; free; embeddings drive RAG quality more than chat-LLM does. |
| Reranking (after retrieval) | **Cohere** rerank-v3, free trial | Big quality lift on RAG; explicit no-training-on-data. **Not yet wired into the live retrieval path** (planned — see §9 task 7); RAG today goes straight from Qdrant retrieval to synthesis with no rerank step. |
| Daily/bulk tasks (news summarize, quick chat, morning brief) | **Groq Llama 3.3 70B** | Fast (~500 tok/s), free 14k req/day, 70B quality. Workhorse. |
| Reasoning tasks (post-mortem, weekly review, "should I rebalance") | **DeepSeek-R1** or **Gemini 2.0 Pro Thinking** | Chain-of-thought. Used rarely; quality matters. |
| Privacy-sensitive prompts | **Local Ollama (Mistral 7B / Llama 3.1 8B)** | Free APIs may log/train on free-tier data. Your portfolio doesn't leave the machine. |
| Fallback (any provider down) | **OpenRouter** free tier | Provider-rotation safety net. |

## 7. Free providers landscape (mid-2026)

| Provider | Free tier | Models worth using | Notes |
|---|---|---|---|
| **Groq** | ~14k req/day, 30 RPM | Llama 3.3 70B, Llama 3.1 8B, Mixtral 8x7B, Gemma 2 9B | Fastest inference; already in `.env`. Verify ToS for no-training. |
| **NVIDIA NIM** | 1000 credits/mo | Llama 3.3 70B, Mistral Large, Mixtral, Nemotron, Phi-3, **NV-Embed-v2 (embeddings)**, **nv-embedqa-e5-v5 (embeddings)** | Embeddings are the killer offering. |
| **Google AI Studio** | 15 RPM, 1500 req/day, 1M tokens/day | Gemini 2.0 Flash, Gemini 2.0 Pro, Gemini Flash Thinking | Generous quotas; long context (1M+); reasoning mode. May train on free-tier data — opt out in console. |
| **DeepSeek** | Free tier (verify) | DeepSeek V3, DeepSeek R1 | Best chain-of-thought reasoning at small cost; strong on finance. China-based; flag if concerning. |
| **OpenRouter** | Rotating free models | Whatever's free that day | Multi-provider routing; one API key for many models. |
| **Cerebras** | Free tier on Llama | Llama 3.1 8B / 70B | ~2000 tok/s — even faster than Groq. |
| **Cohere** | Free trial tier | Command-R+, Command-R, Embed v3, **Rerank v3** | Strong for retrieval; explicit no-training-on-data on trial. |
| **GitHub Models** | ~50 req/day | GPT-4o-mini, Llama 3, Phi-3 | Free GPT-class quality if you have GitHub. Microsoft data terms. |
| **Cloudflare Workers AI** | 10k neurons/day | Llama 3.1, Mistral, embedding models | Cheap once free tier exhausted. |
| **Hugging Face Inference API** | Limited free use | Many open models | Variety; experimental; no SLA. |

Skipped: Together AI (only $1 signup credit), Mistral La Plateforme (small free, less variety), Anthropic (no free tier).

## 8. Implementation pattern

Use **LiteLLM** (https://github.com/BerriAI/litellm) — single Python interface to 100+ providers. MIT licensed. Replaces direct provider SDKs:

```python
litellm.completion(model="groq/llama-3.3-70b-versatile", messages=[...])
litellm.completion(model="ollama/mistral:7b-instruct", messages=[...])
litellm.completion(model="nvidia_nim/meta/llama-3.3-70b-instruct", messages=[...])
litellm.completion(model="gemini/gemini-2.0-flash", messages=[...])
```

Add `pfip/agent/router.py`:
- Inputs: task type + sensitivity classification
- Output: model identifier + provider
- Routing logic per Section 6 of this doc
- Fallback chain if primary fails (Groq → Gemini → OpenRouter → Ollama)

The privacy classifier scans the prompt for:
- Holdings table identifiers (asset symbols user owns)
- Personal pronouns ("my", "I")
- Sensitive nouns ("portfolio", "tax", "holdings", "ITR", "P&L")

If detected → local Ollama only. Else → cloud router.

## 9. Tasks for tracker

When LLM router is on the work plan:

1. Add LiteLLM to backend dependencies
2. Implement `pfip/agent/router.py` with task classifier + privacy detector
3. Wire `pfip/agent/morning_brief.py` to use router
4. Wire `pfip/agent/post_mortem.py` to use router (forced to reasoning model)
5. Wire `pfip/agent/chat.py` to use router with privacy detection
6. Add NVIDIA NIM embedder, swap from local nomic-embed-text in KB ingest
7. Add Cohere reranker after Qdrant retrieval
8. Update `.env.example` with all new provider keys
9. Add provider health-check endpoint to `/api/v1/health/providers`
10. Add fallback chain: if primary provider 5xx or rate-limited, try next; if all fail, return graceful error

## 10. Open questions / future iterations

- **Benchmark FinGPT / Llama-3.1-8B+LoRA / Qwen-2.5 / DeepSeek-R1** on FinQA + FinanceBench + custom finance eval. Output: comparison doc with numbers, pick the long-term primary. Until then: routing per Section 6 is provisional.
- **Cohere rerank vs no rerank** measured on RAGAS — confirm the lift before making it required.
- **Privacy classifier accuracy** — measure false-positive rate (sending public prompts to local unnecessarily) vs false-negative rate (sending sensitive prompts to cloud accidentally). Latter matters more.
- **OpenAI / Anthropic paid tier consideration** — if free tiers degrade, what's the upgrade path? Anthropic Claude has explicit no-training; OpenAI has API tier (no-training). Pricing modest at solo usage volumes.

---

*Last updated: 2026-06-04 (privacy hardening; reranker honesty note).*
