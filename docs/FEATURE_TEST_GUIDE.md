# PFIP — Feature Guide & End-to-End Test Checklist

**Purpose:** every PFIP feature, pin-to-pin — what it's *meant* to do (ideal
goal), what powers it, and **exactly how to test it end-to-end** in the live app.
Tick the checkbox by each feature to record whether it works in the real world.

**Two ways to use this doc:**
1. **Manual walkthrough** — go feature by feature (Sections 1–7B), run each
   "Test", tick the box.
2. **Full audit** — hand the **⭐ Evaluation Prompt** (just below Section 0) to a
   tester or AI agent; it drives a paying-customer-grade review of every feature +
   a missing-features wishlist.

> **Golden rule of the whole product:** PFIP is a **decision-support & research**
> tool, *not* an execution or advice engine. It never places trades and never
> says "buy/sell". Everything is: "here's the data + reasoning; you decide."

> Companion docs: `FEATURES.md` (internal capability inventory), `OPS_VERIFY.md`
> (curl-level live checks). This file is the **human test walkthrough**.

---

## 0. Before you test — access & setup

| Item | Value |
|---|---|
| **App URL** | https://apps.tail1d9a60.ts.net:8443 |
| **Login** | Your email + password (single-user). Everything is behind auth. |
| **AI models** | Groq (Llama-3.3-70B) for chat/research + NVIDIA NIM (embeddings) — both live, free tier |
| **Data cadence** | Nightly pipeline at **02:30 UTC** ingests prices, news, fundamentals, macro |

**How data flows (mental model):** Nightly pipeline → ingest (prices/news/
fundamentals/macro from ~20 live sources) → dedupe/entity-link/classify news →
compute features/regime/signals → store in TimescaleDB. The UI + chat + research
read from that store; Deep Research also fetches **live on-demand**.

---

## ⭐ THE EVALUATION PROMPT — copy-paste this to run a full real-world audit

Hand this prompt (together with this document and access to the live app) to a
capable evaluator — a person, or an AI agent that can drive the browser. It makes
them behave like a **demanding paying customer** and produce a feature-by-feature
verdict plus a wishlist of what's missing. **The single most important question it
must answer for every feature: "does this actually work in the real world, with
live data — and is it useful enough that I'd pay for it?"**

```text
ROLE
You are a prospective PAYING CUSTOMER evaluating "PFIP", a personal financial
intelligence platform (a research/decision-support "Jarvis" for investing — it
covers crypto, Indian equities, US equities, and metals). You are skeptical,
detail-oriented, and you only pay for tools that work reliably in the real world.
You are NOT the developer; you judge it purely as an end user.

INPUTS YOU HAVE
1. The live app (URL + login provided separately).
2. The document "FEATURE_TEST_GUIDE.md" which lists every feature, its ideal
   goal, how to test it, and what to expect.

YOUR TASK — do ALL of the following, thoroughly, feature by feature.

PART A — Test every single feature end to end.
Go through EVERY feature in the guide (Sections 1–7B — Dashboard, Watchlist,
Signals, Events, Themes, Diligence, Deep Research, Holdings, Net worth, Benchmark,
What-if, Stress test, Shadow, Tax, Loss harvesting, Goals, SIP, Journal, Chat,
Perspectives, Calibration, Backtest, Source health, Schedules, Models, Settings,
and all 7B cross-cutting features). Do NOT skip any. For EACH feature:
  1. Open its link/route.
  2. Perform the exact "Test" steps in the guide.
  3. VALIDATE THE IDEAL GOAL: does the feature actually deliver its stated goal
     using REAL, live data — not blanks, placeholders, zeros, or errors?
  4. Assign a WORKS verdict: PASS / PARTIAL / FAIL — with concrete evidence
     (what you saw: numbers, screenshots-in-words, error text, load time).
  5. Assign a REAL-WORLD IMPACT rating: HIGH / MEDIUM / LOW — i.e. how much this
     feature would actually help a real investor make/save money or decisions,
     with a one-line justification.
  6. Note problems: empty states, wrong/stale data, confusing UX, slowness (state
     the seconds), anything that breaks trust.
  7. Suggest a concrete improvement to how the feature SHOULD work to be
     genuinely useful.

PART B — Judge real-world reliability (this is the whole point).
- Is the DATA real and fresh? Cross-check /ops/sources — are sources healthy or
  stale/failing? Would you trust the numbers with your own money?
- Does it handle failure gracefully (a source down, a name that doesn't resolve,
  a slow model) without breaking or lying?
- Does the AI (Chat, Deep Research, Morning brief) give GROUNDED, cited answers,
  or does it hallucinate? Try to catch it inventing a financial figure.
- Rate overall real-world readiness: PRODUCTION-READY / USABLE-WITH-GAPS /
  NOT-READY, and say exactly why.

PART C — As a paying customer, what's MISSING?
List the features you would EXPECT this product to have but it doesn't (or does
poorly). For EACH proposed feature give:
  - Name.
  - Goal (what problem it solves for the user).
  - How it should work: inputs → processing → output the user sees.
  - Why it matters / who it helps.
  - Priority: P0 (must-have to pay) / P1 (would sway me) / P2 (nice-to-have).
Think broadly: alerts you'd actually act on, mobile/notifications, broker/exchange
sync, portfolio auto-import, richer fundamentals (balance sheet, cash flow, peer
comparison), screeners, scenario planning, options/derivatives, better India
coverage, explainability, personalization, export/reporting, etc. Prioritize what
makes it trustworthy and useful in the REAL WORLD, not flashy extras.

PART D — Verdict.
  - Would you pay for this today? Yes / No / Not yet — and the honest reason.
  - What is the ONE killer feature that could sell it?
  - What is the ONE dealbreaker that must be fixed first?
  - A real-world readiness score out of 10, with justification.

OUTPUT FORMAT
1. A table: | Feature | Works (Pass/Partial/Fail) | Impact (H/M/L) | Evidence | Fix needed |
   — one row PER feature, none skipped.
2. A "Reliability" section (Part B findings).
3. A "Missing features I'd expect as a paying customer" section (Part C), ordered
   by priority, each with the full spec above.
4. A "Verdict" section (Part D).
Be specific and evidence-based. Quote real numbers/errors you saw. No vague praise.
```

> **How to use it:** open the app side-by-side with this guide, run the prompt,
> and fill in the checkboxes in Sections 1–7B as you confirm each feature. The
> prompt's Part C output becomes the next roadmap.

---

## 1. Overview

### 1.1 Dashboard  `/`
- [ ] **Ideal goal:** one-glance market pulse — a primary price chart with
  timeframe toggles plus quick cards.
- **Test:** Open `/`; toggle chart ranges **1W / 1M / 3M / 6M / 1Y**.
- **Expect:** chart redraws with daily data each range; price/volume readout
  updates; a freshness badge shows how old the last bar is.
- **Caveat:** all ranges use **daily** bars by design (no intraday data).

---

## 2. Markets

### 2.1 Watchlist  `/watchlist`
- [ ] **Ideal goal:** your tracked universe, segmented by class (Crypto / India /
  US / Metals) with last price, change, freshness.
- **Test:** Open `/watchlist`; add a symbol (e.g. `INFY.NS`); remove one.
- **Expect:** rows grouped by category; price + % change + stale badge; add/remove
  persists on refresh.

### 2.2 Signals  `/signals`
- [ ] **Ideal goal:** experimental ML direction signals per asset with confidence.
- **Test:** Open `/signals`.
- **Expect:** assets with direction + confidence + horizon, labelled experimental.
- **⚠️ Honest status:** signals have **no demonstrated edge** in backtest — a
  research artifact, not a trade instruction. Intentionally surfaced, not hidden.

### 2.3 Events (catalysts)  `/events`
- [ ] **Ideal goal:** auto-detect market-moving events from news — contract wins,
  earnings, M&A, upgrades/downgrades, regulatory, buybacks — tagged to a ticker.
- **Test:** Open `/events`; change **window** (7/30/90d) and **min materiality**;
  click **🔬 Research** on any row.
- **Expect:** list filters; the Research button jumps to Deep Research pre-filled
  with that ticker and auto-runs a dossier.
- **Caveat:** keyword-based extraction → occasional false positives; advisory.

### 2.4 Themes  `/themes`
- [ ] **Ideal goal:** surface market themes/narratives and the candidate stocks
  that could benefit, *with evidence*.
- **Test:** Open `/themes`.
- **Expect:** current themes; each expands to a rationale + candidate tickers with
  cited reasoning.

### 2.5 Research (Diligence)  `/diligence`
- [ ] **Ideal goal:** structured due-diligence for a **tracked** symbol — price,
  key metrics, filings, insider, flows, on-chain, model read.
- **Test:** Open `/diligence`; search a tracked symbol (`RELIANCE.NS`, `AAPL`).
- **Expect:** price + change, key ratios, recent filings/news, an honest summary
  with a data-coverage note + experimental disclaimer.

### 2.6 Deep Research  `/research`  ⭐ flagship
- [ ] **Ideal goal:** type **any** company by name — tracked or not — and get a
  cited decision-support dossier: what they do, financial health, recent
  developments, bull case, bear case, risks, sentiment, what to verify.
- **Powered by:** LLM name→ticker → **live fundamentals** (screener.in for India,
  Alpha Vantage for US, yfinance fallback) → news → LLM synthesis. Fundamentals
  are persisted so repeat searches accumulate history.
- **Test A (India, untracked):** search **`Waree Energies`** → "Not tracked"
  badge; **Key fundamentals** grid via **screener** (P/E, ROCE, ROE, mkt cap,
  book value); a full dossier; recent news.
- **Test B (US):** search **`NVIDIA`** → metrics grid with a blue **Live ·
  alphavantage** tag; dossier.
- **Test C (deep link):** from `/events` click **Research** → lands here
  pre-filled and auto-runs.
- **Caveat:** a truly obscure name may not resolve → it says so honestly rather
  than inventing numbers.

---

## 3. Portfolio

### 3.1 Holdings  `/portfolio`
- [ ] **Ideal goal:** your positions with live valuation, cost basis, P&L, weights.
- **Test:** Open `/portfolio`; add a holding (symbol, qty, buy price).
- **Expect:** market value, unrealised P&L, portfolio weight compute; totals
  update; persists on refresh.

### 3.2 Net worth  `/net-worth`
- [ ] **Ideal goal:** total net-worth timeline across assets, FX-normalised.
- **Test:** Open `/net-worth`.
- **Expect:** a net-worth line over time + a current total in your base currency.

### 3.3 Benchmark  `/benchmark`
- [ ] **Ideal goal:** compare your portfolio return vs a benchmark (NIFTY/SPY).
- **Test:** Open `/benchmark`; pick a benchmark + window.
- **Expect:** your return vs benchmark return + a relative over/under figure.

### 3.4 What-if  `/what-if`
- [ ] **Ideal goal:** simulate a hypothetical change ("what if I'd bought X / sold
  Y") and see the impact.
- **Test:** Open `/what-if`; define a scenario.
- **Expect:** a before/after comparison of value or return.

### 3.5 Stress test  `/stress-test`
- [ ] **Ideal goal:** shock the portfolio (crash, rate spike, INR move) and see
  estimated drawdown.
- **Test:** Open `/stress-test`; apply a scenario.
- **Expect:** estimated impact per shock, per position and total.

### 3.6 Shadow  `/shadow`
- [ ] **Ideal goal:** a paper/shadow portfolio to track ideas vs actual, with a
  return/Sharpe comparison.
- **Test:** Open `/shadow`.
- **Expect:** shadow positions + a comparison to your real portfolio's outcome.

---

## 4. Tax (India)

### 4.1 Tax  `/tax`
- [ ] **Ideal goal:** India capital-gains view — realised STCG/LTCG + exportable
  report.
- **Test:** Open `/tax`; export the report.
- **Expect:** gains split short/long term; a downloadable report file.

### 4.2 Loss harvesting  `/tax/harvest`
- [ ] **Ideal goal:** identify positions at a loss that could offset gains.
- **Test:** Open `/tax/harvest`.
- **Expect:** candidate positions with unrealised losses + potential offset.
- **Caveat:** educational only — not tax advice; verify with a CA.

---

## 5. Tools

### 5.1 Goals  `/goals`
- [ ] **Ideal goal:** define financial goals (target + date) and track progress /
  required contribution.
- **Test:** Open `/goals`; add a goal.
- **Expect:** progress toward target + monthly contribution needed.

### 5.2 SIP  `/sip`
- [ ] **Ideal goal:** track systematic investments and compute XIRR.
- **Test:** Open `/sip`; add SIP entries.
- **Expect:** invested vs current value + an **XIRR** figure.

### 5.3 Journal  `/journal`
- [ ] **Ideal goal:** a decision journal — log entries with rationale to review
  later.
- **Test:** Open `/journal`; add an entry.
- **Expect:** entry saved + listed with timestamp; persists on refresh.

### 5.4 Chat (AI assistant)  `/chat`  ⭐
- [ ] **Ideal goal:** conversational assistant that sees your portfolio, the
  knowledge base (Graham/Wyckoff/etc.), and live news — answers questions,
  explains moves, and can **research any company by name** inline.
- **Powered by:** SSE streaming over the agent graph; Groq LLM; RAG (Qdrant) +
  news + DB grounding; live fundamentals for untracked names.
- **Test:** Open `/chat` (or the ✨ bubble anywhere). Ask:
  - "What's happening with Reliance?" → grounded answer.
  - "research Waree Energies — fundamentals and bull/bear" → real numbers +
    reasoning, cited `db://research/...`.
- **Expect:** answers **stream token-by-token**, cite sources, never place trades
  or give direct buy/sell advice.
- **Caveat:** portfolio/sensitive questions prefer local model but fall back to
  cloud (Groq) since the VM has no GPU.

### 5.5 Perspectives  `/perspectives`
- [ ] **Ideal goal:** multi-persona take (value / macro / risk lenses) so you see
  several viewpoints, not one.
- **Test:** Open `/perspectives`; ask about an asset/topic.
- **Expect:** distinct persona sections each reasoning differently.

### 5.6 Calibration  `/calibration`
- [ ] **Ideal goal:** show how well the model's confidence is calibrated (do 70%
  calls happen ~70% of the time?).
- **Test:** Open `/calibration`.
- **Expect:** a calibration curve / reliability metrics for past signals.

### 5.7 Backtest  `/backtest`
- [ ] **Ideal goal:** backtest a strategy/signal over history.
- **Test:** Open `/backtest`; run a backtest.
- **Expect:** equity curve + summary stats (return, Sharpe, drawdown).

---

## 6. Operations (reliability)

### 6.1 Source health  `/ops/sources`  ⭐
- [ ] **Ideal goal:** per-source observability — is each data source pulling, when
  did it last succeed, is anything stale/failing. **This is how you know the data
  is real.**
- **Test:** Open `/ops/sources`.
- **Expect:** ~20 sources with last-run time, last row count, consecutive-failure
  count, and a healthy/stale/failing status.
- **Use it to verify:** after a nightly run, `alphavantage` + `newsdata` show rows
  with 0 failures (confirms the API keys are live).

### 6.2 Schedules  `/ops/schedules`
- [ ] **Ideal goal:** see scheduled jobs (nightly pipeline, retrain) + status.
- **Test:** Open `/ops/schedules`.
- **Expect:** the pipeline/retrain schedule + last-run outcome.

### 6.3 Models  `/ops/models`
- [ ] **Ideal goal:** model registry — champion, versions, validation gate status.
- **Test:** Open `/ops/models`.
- **Expect:** registered models with champion/challenger status.

---

## 7. Settings  `/settings`
- [ ] **Ideal goal:** app configuration (preferences, feature toggles).
- **Test:** Open `/settings`; change a setting; save.
- **Expect:** setting persists on refresh.

---

## 7B. Cross-cutting & AI features (surfaced in-context, no standalone nav page)

These are real capabilities that appear inside other pages (dashboard cards, the
chat, a notifications bell, onboarding) rather than as their own menu item — test
them too.

### 7B.1 Self-custody wallets
- [ ] **Ideal goal:** track on-chain crypto you hold in your own wallets (BTC/ETH/
  SOL addresses) so net worth includes self-custodied coins, not just exchange
  holdings.
- **Powered by:** mempool.space (BTC), Etherscan (ETH), Solscan (SOL).
- **Test:** add a public wallet address (in Settings / Net-worth area); refresh.
- **Expect:** the wallet's balance is fetched and folded into net worth.

### 7B.2 Proactive alerts / notifications
- [ ] **Ideal goal:** surface things worth your attention without asking — a source
  went stale, a big price move, a freshness-SLA breach, a detected catalyst.
- **Powered by:** the alerts engine + `notifications/recent`.
- **Test:** open the notifications area (bell) after a pipeline run.
- **Expect:** recent alerts listed; a stale/failing source generates one.

### 7B.3 Changes today
- [ ] **Ideal goal:** a "what moved and why" snapshot for the day — top movers in
  your universe with linked news.
- **Test:** on the Dashboard, find the changes-today card.
- **Expect:** today's notable movers with % change and a news hook.

### 7B.4 Morning brief (AI)
- [ ] **Ideal goal:** an AI-written daily briefing — overnight moves, your
  portfolio's exposure, notable news/catalysts, what to watch.
- **Powered by:** LLM over portfolio + news + events (`agent/morning-brief`).
- **Test:** open the morning brief (dashboard / briefings).
- **Expect:** a concise, grounded narrative referencing your actual holdings/news.

### 7B.5 Weekly review (AI)
- [ ] **Ideal goal:** a weekly retrospective — how your portfolio did, what changed,
  themes that played out.
- **Test:** open the weekly review (`agent/weekly-review`).
- **Expect:** a week-over-week summary grounded in your data.

### 7B.6 Post-mortem (AI)
- [ ] **Ideal goal:** analyse a past decision/trade — what the thesis was, what
  happened, what to learn (ties into the Journal).
- **Test:** run a post-mortem on a journal entry / position (`agent/post-mortem`).
- **Expect:** a structured lessons-learned write-up, not a buy/sell call.

### 7B.7 arXiv research digest (AI)
- [ ] **Ideal goal:** digest recent quantitative-finance academic papers into plain
  summaries so you stay current on methods.
- **Test:** open the arXiv digest (`agent/arxiv-digest`).
- **Expect:** recent q-fin papers summarised with takeaways.

### 7B.8 Onboarding / setup
- [ ] **Ideal goal:** first-run bootstrap — seed a watchlist, optionally load demo
  data so the app isn't empty on day one.
- **Test:** check setup status; run bootstrap / demo seed.
- **Expect:** a starting watchlist + populated views without manual entry.

---

## 8. Data sources behind the app

| Category | Sources | Notes |
|---|---|---|
| **Crypto prices** | CCXT (Binance/etc.), CoinGecko | fresh daily |
| **US equities** | Tiingo → yfinance → Stooq | yfinance rate-limited on VM |
| **India equities** | NSE/BSE bhavcopy, jugaad, yfinance | |
| **India MF** | AMFI NAV | keyless |
| **Fundamentals** | Finnhub (US), **screener.in** (India), **Alpha Vantage** (US live) | screener powers Deep Research India |
| **Macro/FX** | FRED, Frankfurter, RBI, World Bank | |
| **News** | RSS, Google News, GDELT, Reddit, **Alpha Vantage**, **NewsData**, Telegram (opt) | dedupe→entity-link→classify→prune |
| **Filings/insider** | SEC EDGAR (US), NSE corp announcements + PIT (India) | |
| **On-chain** | mempool.space, DeFiLlama | crypto fundamentals |

**Reliability principle:** every source no-ops safely without its key and records
its health, so a broken source shows up on `/ops/sources` the day it breaks.

---

## 9. Known limitations (be honest while testing)

- **Signals have no proven edge** — experimental, labelled as such.
- **No intraday data** — daily bars only, by design.
- **yfinance rate-limited** from the datacenter IP — Deep Research uses screener
  (India) / Alpha Vantage (US) as the reliable paths.
- **Local LLM (Ollama) is down on the VM** (no GPU) — chat/research use Groq.
- **Alpha Vantage free tier = 25 calls/day** — US Deep Research + AV news share it.
- **Not investment advice** — every AI output is decision-support with a
  disclaimer; verify independently.

---

## 10. Suggested test order (fastest path to "does it work?")

1. **Login** → **Dashboard**, toggle chart ranges.
2. **/ops/sources** → confirm sources healthy (proves the data is real).
3. **/research → "Waree Energies"** and **"NVIDIA"** → flagship.
4. **/chat → "research Waree Energies"** → streaming AI + grounding.
5. **/events → Research button** → the one-click loop.
6. **/watchlist, /portfolio** → add/remove, valuations.
7. Walk the rest (Tax, Goals, SIP, Net worth, Benchmark, Stress test, Shadow,
   Perspectives, Calibration, Backtest, Schedules, Models, Settings).

Mark each checkbox as you go. Anything unchecked → note the page + what you saw,
and it can be fixed.
