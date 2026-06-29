# PFIP Roadmap — toward a reliable personal-finance AI assistant

PFIP's goal is a **trustworthy personal-finance intelligence assistant** ("Jarvis"):
categorised market coverage, insight into *why* things move, detection of catalysts
and themes, and a conversational agent grounded in real data and your portfolio.

The guiding principle, learned the hard way: **reliable in the real world beats
green-on-paper.** Tests passing is necessary but not sufficient — a pipeline can
run, every endpoint can return `200`, and the app can still be silently broken
(stale data, empty news, a dead chat). So every phase is built on a hardened data
+ observability layer, and "done" means *verified against live data*, not just CI.

Honest scope: research consistently shows LLM/ML agents rarely beat buy-and-hold
(e.g. StockBench). PFIP is therefore an **insight / research / explanation**
assistant that makes *you* a sharper investor — it surfaces themes, catalysts and
the "why", with evidence — **not** an oracle that predicts winners or auto-trades.

---

## Reliability principles (apply to every phase)

1. **Assume sources fail.** Multiple providers per data type with automatic
   fallback; never a single point of failure.
2. **Observability before features.** Every source reports health; staleness
   raises an alert. You're told when something breaks — you don't discover it.
3. **Graceful degradation.** A dead dependency degrades (RAG without Qdrant, chat
   without local LLM) — it never takes the surface down.
4. **Honest UI.** Show "stale" / "experimental / no proven edge" rather than
   presenting unreliable data as fact.
5. **Tests that check data, not just HTTP.** Assert freshness + presence, not 200s.

---

## Phase 0 — Reliability foundation ✅ (done)

Hardened the base so the rest can be trusted. (See git history `fix(reliability)`.)

- **Source observability + freshness SLA alerts** — every ingest source records to
  `source_health`; the daily run alerts when a class's data goes stale.
- **Per-asset news fixed** — query `entity_tickers` + alias-based entity-linking
  ("Bitcoin"/"Reliance" → tickers). News went from 0 to surfaced.
- **Chat fixed** — cloud fallback (Groq→NIM→Ollama) so the assistant works without
  a local LLM; embeddings/reasoning stay strictly local. RAG degrades gracefully.
- **Equity data redundancy** — yfinance fallback for US + India (was 5–7d stale);
  `get_candles` shows the freshest source. MF (AMFI) + macro (FRED) wired in.
- **Honest UI** — daily-range chart (no empty 1D/1W), signals labelled experimental,
  changes-today fixed.
- **Data-freshness monitor** — e2e suite asserts fresh + non-empty data + live chat.

---

## Phase 1 — Categorised universe + reliability dashboard

Make the four asset classes first-class: **Crypto · India · US · Metals**.

- Wire the dormant metals adapters (LBMA gold/silver, EIA, futures) into the daily
  pipeline; add gold/silver to the watchlist.
- Category-segmented dashboards (overview, movers, regime per class).
- Surface `source_health` as a reliability panel (per-source freshness, last error).

**Reliability bar:** each class has ≥2 data sources; staleness visibly flagged.

## Phase 2 — Narrative "why" engine

For any asset or move, explain it from the (now-working) news + KB.

- "Why did X move?" → the agent cites the catalysts it ingested, with sources +
  confidence, and an explicit "insufficient evidence" path (no hallucinated causes).
- Per-asset "what's driving this" cards on the dashboard.

**Reliability bar:** every claim cites a source; abstains when evidence is thin.

## Phase 3 — Event / catalyst detector

Surface discrete catalysts: tenders/large orders won, earnings surprises, upgrades,
regulatory actions, M&A.

- Classify ingested news/filings into typed events, link to the affected ticker,
  score materiality. (Borrow TradingAgents' News-Analyst pattern.)
- An "events" feed + alerts for watchlist names.

**Reliability bar:** events deduped + source-scored; precision tracked over time.

## Phase 4 — Thematic insight engine

Theme → candidate beneficiaries *with evidence* (e.g. "AI buildout" → chips, power,
cooling), the "spot it early" idea — as a **research aid that proposes candidates
for you to judge**, not auto-picks.

- LLM + KB + a light supply-chain/relationship map to rank thematic exposure.
- Backtest theme baskets honestly (vs benchmark), report with full uncertainty.

**Reliability bar:** every candidate carries its evidence + a clear "not advice" frame.

## Phase 5 — Proactive "Jarvis" layer

- Proactive morning/weekly briefings grounded in your portfolio + the day's events.
- Multi-persona reasoning (value / macro / risk views) à la ai-hedge-fund.
- Fully conversational, memory of your context, voice-optional.

**Reliability bar:** proactive nudges are rate-limited, grounded, and dismissible.

---

## References (inspiration, not dependencies)
- [TradingAgents](https://github.com/tauricresearch/tradingagents) — multi-agent news/fundamental/risk workflow
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — multi-persona reasoning
- [OpenBB](https://github.com/OpenBB-finance/OpenBB) — data platform + agent/MCP design
- [FinRobot / FinGPT](https://github.com/AI4Finance-Foundation/FinRobot) — layered financial-agent architecture
- [StockBench](https://arxiv.org/abs/2510.02209) — sober baseline: agents rarely beat buy-and-hold
