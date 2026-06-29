# PFIP Phase Plan (detailed) — Phases 1–5

Companion to [ROADMAP.md](../ROADMAP.md). This breaks each phase into concrete
work items, the data it needs, existing code to reuse, the reliability bar that
defines "done", effort (S/M/L), dependencies, and risks. Reliability-first:
every phase assumes sources fail, degrades gracefully, and ships with data-level
tests (not just HTTP 200s).

**Sequencing & prerequisites**
- **P0 (done):** observability, news, chat, data redundancy.
- **Cross-cutting prerequisite — fix VM egress.** `source_health` shows Yahoo
  (yfinance), FRED, and AMFI are unreachable from the VM. P1 metals + P4 themes
  want more sources, so resolve VM DNS/egress (or pick reachable providers) first.
- **LLM cost guardrails** (caching + rate limits) land in P2 and are reused by P3–P5.
- Rough order: **P1 → P2 → P3 → P4 → P5** (each builds on the prior).

---

## Phase 1 — Categorised universe + reliability dashboard  (effort: M)

**Goal:** Crypto · India · US · **Metals** as first-class categories, plus a
reliability panel so data health is glanceable.

**Work items**
1. **Asset-class model.** Add `asset_class` to the watchlist (or derive via a
   shared classifier — reuse `_asset_class()` in `scripts/run_daily_pipeline.py`).
   Expose it in `GET /watchlist` and the contracts.
2. **Metals data.** Wire the dormant commodity adapters into `stage_ingest`:
   `pfip/ingest/commodities/{lbma_gold,lbma_fix,eia,yfinance_futures,nasdaq_data_link}`.
   Add instruments to the watchlist — prefer **ETF/INR proxies that already price
   reliably** (`GLD`, `SLV`, `GOLDBEES.NS`, `SILVERBEES.NS`) over spot, since LBMA
   reachability from the VM is unverified. Gold/silver in INR via the FX layer.
3. **Category-segmented UI.** Add a class filter/tabs (Crypto/India/US/Metals) to
   `app/page.tsx` (dashboard), `app/watchlist`, `app/signals`. Per-class overview
   card: count, top movers, regime mix.
4. **Reliability dashboard.** Enhance `app/ops/sources` (already reads
   `/health/sources`) to show per-source freshness, last error, and
   `consecutive_failures`; add a compact "data health" badge on the dashboard.

**Data/sources:** commodity adapters + ETF proxies; existing FX for INR conversion.
**Reuse:** `_asset_class`, `source_health`, `Stale/FreshnessBadge`, ops/sources page.
**Reliability bar:** every class has ≥2 reachable sources; staleness visibly flagged.
**Risks:** LBMA/EIA egress from VM (use ETF proxies as the reliable path); INR
gold conversion correctness.

---

## Phase 2 — Narrative "why" engine  (effort: M)

**Goal:** explain *why* an asset moved, grounded in the (now-working) news + KB,
with citations and an honest "insufficient evidence" path.

**Work items**
1. **`/assets/{symbol}/explain` endpoint.** Gather: the price move over a window,
   the news entity-linked to that symbol in the window (P0 fix makes this real),
   the regime, and relevant KB passages → an LLM synthesises a **cited**
   explanation. Reuse the retrieval nodes in `pfip/agent/graph.py`
   (`node_retrieve_kb`, news retrieval) + `pfip/kb/search.py`.
2. **Guardrails.** Mandatory source citations; abstain ("no clear catalyst found")
   when evidence is thin — never invent a cause. Attach a confidence label.
3. **LLM cost guardrails (cross-cutting).** Cache explanations per `(symbol, date)`
   in Redis; rate-limit; route via `TaskType.QUICK_SUMMARY`/`CHAT_PUBLIC`.
4. **Frontend.** "What's driving this" card on the asset deep-dive
   (`components/portfolio/deep-dive-panel.tsx`) + a "Why?" action on movers.

**Data/sources:** entity-linked news, KB (Qdrant — verify reachable), regime, OHLCV.
**Reuse:** agent graph retrieval, kb/search, reranker, llm_client router.
**Reliability bar:** every claim cites a source; abstains when thin; cached to bound cost.
**Risks:** hallucinated causation (mitigate with strict cite-or-abstain prompt +
eval); Qdrant availability (degrade to news-only).

---

## Phase 3 — Event / catalyst detector  (effort: L)

**Goal:** surface discrete catalysts (tenders/large orders won, earnings
surprises, upgrades, M&A, regulatory, buybacks, guidance) per ticker.

**Work items**
1. **Event taxonomy** — enumerate typed event kinds + a materiality rubric.
2. **Extraction pipeline** — classify ingested news + filings into typed events,
   link to the affected ticker, score materiality. Reuse `news/_pipeline`,
   `us_equities/sec_edgar`, `indian_equities/{nse_corporate_announcements,
   nse_pit_disclosures,nse_fii_dii}`. LLM extraction via `TaskType.BULK_PREPROCESS`.
3. **`events` table + migration** — `(id, ticker, kind, materiality, summary,
   source_url, occurred_at, dedup_key)`. Add to the daily pipeline as a stage.
4. **Dedup + source-reliability scoring** — collapse near-duplicates; weight by
   source trust (borrow TradingAgents' News-Analyst idea).
5. **API + UI + alerts** — `/events` feed + per-asset events; watchlist event
   alerts via `pfip/alerts/dispatcher.py` (`AlertKind` — add `CATALYST`); an
   "Events" page.

**Data/sources:** news, SEC EDGAR, NSE corp announcements/PIT/FII-DII.
**Reuse:** news pipeline, filing adapters, alerts dispatcher, entity-linker.
**Reliability bar:** events deduped + source-scored; extraction precision tracked
on a labelled sample over time.
**Risks:** extraction precision/recall; filing-source egress; alert noise (gate by
materiality + rate cap).

---

## Phase 4 — Thematic insight engine  (effort: L / hardest)

**Goal:** theme → candidate beneficiaries **with evidence** (the "spot AI early →
NVIDIA" idea) as a research aid that proposes candidates for *you* to judge.

**Work items**
1. **Theme catalogue** — curated themes (AI buildout, semis, power/grid, EV,
   defense, renewables, India PLI/infra…) with descriptions + seed terms.
2. **Reference universe + sector/industry map** — beneficiaries need a broader
   universe than the watchlist. Add a companies→sector/industry/theme reference
   dataset (this is the data-heavy lift). Light supply-chain/relationship map.
3. **Beneficiary ranking** — LLM + KB + the relationship map score thematic
   exposure per company, each with **evidence** (which news/filings/segments tie
   it to the theme). Reuse KB search + events (P3) + news.
4. **Theme baskets + honest backtest** — construct candidate baskets; backtest vs
   benchmark (reuse `scripts/backtest_signals.py` patterns + `portfolio/benchmark`);
   report with full uncertainty and a "not advice" frame.
5. **Frontend** — themes explorer; per-theme beneficiary list with evidence + the
   backtest caveats.

**Data/sources:** sector/industry reference data, KB, events, news, OHLCV.
**Reuse:** kb/search, events (P3), backtest engine, benchmark.
**Reliability bar:** every candidate carries its evidence + uncertainty; backtests
are honest (out-of-sample, vs benchmark), never presented as predictions.
**Risks:** data acquisition (sector/supply-chain mapping is the crux); LLM
hallucinating spurious links (require evidence per candidate); overfitting baskets.

---

## Phase 5 — Proactive "Jarvis" layer  (effort: M, ongoing)

**Goal:** proactive, grounded, conversational assistant with memory.

**Work items**
1. **Proactive briefings** — upgrade morning/weekly briefs
   (`pfip/agent/morning_brief.py`, `scripts/run_weekly`) to weave in P3 events +
   P2 narratives, grounded in the portfolio.
2. **User-context memory** — persist goals, risk prefs, holdings context across
   sessions (a `user_context` store) so the agent personalises and remembers.
3. **Multi-persona reasoning** — value / macro / risk views annotate a question
   (à la ai-hedge-fund); surfaced as distinct perspectives, not a single verdict.
4. **Proactive notifications** — nudges via `pfip/alerts/dispatcher.py` (Telegram
   already wired), **rate-limited + dismissible + grounded**.
5. **Conversational depth** — multi-turn memory, richer tool use (extends
   `pfip/agent/tools.py`); voice-optional (stretch).

**Reuse:** morning_brief, weekly_review, alerts (Telegram), agent graph + tools.
**Reliability bar:** proactive output is rate-limited, grounded (cites P2/P3),
and dismissible; never spammy, never ungrounded.
**Risks:** notification fatigue (strict caps); persona outputs disagreeing
confusingly (present as views, not advice); memory privacy.

---

## Cross-cutting tracks (run alongside)
- **Infra reliability:** fix VM egress (Yahoo/FRED/AMFI); confirm Qdrant
  reachable; keep `source_health` + freshness alerts honest. *(prereq for P1/P4)*
- **LLM cost & latency:** response caching, rate limits, token budgets. *(from P2)*
- **Evaluation harness:** labelled samples to track narrative faithfulness (P2),
  event precision (P3), theme-basket backtests (P4) — so quality is measured, not
  assumed.
- **Tests:** extend the `data-freshness` e2e monitor with per-phase data assertions
  (events present, explanations cited, theme evidence non-empty).

## Definition of done (per phase)
1. Feature works **against live data** (verified by probe, not just unit tests).
2. Degrades gracefully when a dependency is down.
3. Has a data-level test in the e2e monitor.
4. Honest UI framing (cited / uncertain / "not advice" where applicable).
5. Deployed green (CI + deploy) and re-probed live.
