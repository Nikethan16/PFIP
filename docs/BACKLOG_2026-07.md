# PFIP — Master Backlog (from the 2026-07 audit)

Everything we found, in one tickable list. Full reasoning lives in
[`PLATFORM_AUDIT_2026-07.md`](PLATFORM_AUDIT_2026-07.md). Priorities: **P0** = do
first (trust/clutter), **P1** = high value, **P2** = later. Effort: S (<1h),
M (a session), L (multi-session).

---

## A. Confirmed bugs — fix these
- [ ] **A1 · P0 · S** — Notification bell is broken: it shows the unread *count* but the dropdown discards the `items` array and says "see Telegram"; empty-state copy still says *"when the backend wires the endpoint"* (stale — it IS wired). → Render the real `items` list (severity, title, body, time) from `/notifications/recent`; fix the copy. *File: `frontend/components/nav/topbar.tsx`.*
- [ ] **A2 · P0 · S** — Signals shown as actionable in the main "Markets" menu, but every call is HOLD @ ~9.8% confidence and the model is below coin-flip (see F). → Demote to "Lab" + keep the "no proven edge" label.
- [ ] **A3 · P0 · S** — **No DB backups exist**; `pfip-backup.timer` never ran. → Enable + verify on the VM (`systemctl enable --now pfip-backup.timer`; confirm a dump lands in `~/pfip-backups`).
- [ ] **A4 · P0 · S** — Weekly scheduler broken: GitHub crons `weekly.yml`/`daily-ingest.yml` `startup_failure` (workflow-file/Actions issue, even on manual dispatch); VM `pfip-weekly.timer` `last_run: null`. → Pick ONE working path (fix GitHub Actions billing/validation, or enable the VM timer) so calibration/diligence/peers auto-populate.
- [ ] **A5 · P0 · S** — Backtest run *was* 500 on real data (NaN/numpy in JSONB) — **FIXED + deployed** this session. Verify it stays green.

## B. Data reliability / config (mostly VM env, not code)
- [ ] **B1 · P0 · S** — US data keys missing on the VM ingest env (Tiingo/Finnhub/Alpha-Vantage read `NO-KEY`) → US prices/fundamentals/statements 9.7d stale, won't self-heal. → Add keys to `~/pfip/backend/.env`, restart `pfip-api` + confirm nightly refresh.
- [ ] **B2 · P0 · S** — `SEC_EDGAR_USER_AGENT` unset on VM → SEC 403s every US filing. → `echo 'SEC_EDGAR_USER_AGENT=Name email' >> ~/pfip/backend/.env` + set the GitHub secret.
- [ ] **B3 · P1 · S** — News corpus is thin (news ingest ~0 rows some runs) → starves Events/Themes/per-name filings. → Add + enable real news providers (NewsData / Marketaux / Benzinga keys).
- [ ] **B4 · P1 · M** — Swap US fundamentals + 5-yr statements from Alpha Vantage (25/day) → **Financial Modeling Prep** (250/day, cleaner statements). Unlocks statements for more names.
- [ ] **B5 · P1 · S** — India fundamentals: consider **Tickertape/Trendlyne** or **Kite Connect** for full statements (screener scrape is top-ratios only).

## C. Restructure / information architecture (25 menu items → 5)
- [x] **C1 · P0 · M** — New IA: **Home · Research · Portfolio · Plan · Lab · Settings** — **DONE** this session. `nav-items.ts` regrouped into 6 sections; `sidebar.tsx` now renders **collapsible** sections (auto-expands the active one). Routes unchanged.
- [x] **C2 · P0 · M** — Merge **Research (`/diligence`) + Deep Research (`/research`)** — **DONE** via `app/(research)/` route group + shared `SectionTabs` (Company research | Deep research). URLs unchanged.
- [x] **C3 · P0 · M** — **Net-worth / Benchmark / What-if / Stress / Shadow / Tax as tabs under Portfolio** — **DONE** via `app/(portfolio)/` route group + `SectionTabs` (Holdings | Net worth | Benchmark | What-if | Stress | Shadow | Tax | Harvest). URLs unchanged.
- [~] **C4 · P0 · S** — Fold **Perspectives** into **Chat** — *decluttered:* moved out of the main nav into **Lab**. Deep "mode inside the chat surface" integration deliberately deferred (lowest value, chat layout is height-constrained); page still works standalone.
- [x] **C5 · P0 · S** — Merge **SIP + Goals + Watchlist + Journal** into a **"Plan"** section — **DONE** (grouping).
- [x] **C6 · P0 · S** — Move **Signals / Calibration / Backtest / Perspectives / Source-health / Schedules / Models** into a collapsed **"Lab"** section — **DONE** (collapsed by default).

## D. New features to build
- [ ] **D1 · P0 · L** — **Broker/exchange auto-import** (Zerodha Kite, Binance, ICICIdirect / CSV). Unlocks real Holdings + Tax + XIRR + Harvest (all currently correct-but-empty).
- [~] **D2 · P0 · M** — **User-defined alerts** — **live-check DONE**. Pure rule engine (`pfip/alerts/rules.py`: price_above/below, pct_up/down_1d); API `/alerts/kinds` + `/alerts/evaluate` (latest close + 1d move); Alerts page (Plan) with locally-saved rules + "Check now". 7 tests. _Follow-up: background firing to bell + Telegram needs a server-side rules table + scheduler (held back to avoid an unverifiable migration before deploy)._
- [x] **D3 · P1 · M** — **Balance-sheet upload → insights** — **DONE**. Pure, unit-tested engine (`pfip/research/balance_sheet.py`): current/quick/D-E/interest-coverage/ROCE + **Altman Z** with zone; best-effort CSV/PDF extraction (echoes parsed fields). API `POST /balance-sheet/analyze` + `/upload`; grounded LLM narrative w/ deterministic fallback (never invents figures). Frontend page under **Research** (upload + manual entry, ratio cards, Z gauge, insights). 10 backend tests. _Follow-ups: xlsx (needs openpyxl), image OCR, peer-compare hookup._
- [x] **D4 · P1 · M** — **Screener** — **DONE**. Pure filter engine (`pfip/research/screener.py`) over canonical key metrics; multi-criterion AND (gt/gte/lt/lte/eq); API `/screener/fields` + `/screener/run` over the stored-fundamentals universe; Research page with criterion builder, results table, locally-saved screens. 7 tests. _Follow-up: server-side saved screens (table)._
- [ ] **D5 · P1 · M** — **Analyst estimates / forward numbers** in Research (FMP/Tickertape).
- [ ] **D6 · P1 · M** — **Corporate-actions + earnings calendar** (real, per-holding).
- [ ] **D7 · P2 · L** — **Mobile PWA + web push**.
- [ ] **D8 · P2 · L** — **Options / F&O (India)** — payoff + greeks.
- [x] **D9 · P1 · L** — **"Learn" module — DONE**. `GET /learn/{symbol}`: price series + biggest swings each matched to a real news catalyst (±3d, never invented) + grounded LLM primer (offline fallback) + educational strategies (DCA/hold/sizing/rebalance/+crypto vol note). Pure move-detection (`pfip/research/learn.py`, 6 tests); Research page with recharts chart + swing markers + "why it moved" cards + primer + strategies. _Follow-ups: progressive depth levels, `explain_asset` tool for E._ · _(original spec:)_ Pick any asset (e.g. Bitcoin) and get a guided, explain-like-I'm-new view: interactive **price chart** + plain-English **"why did it move"** annotations on the notable dips/rallies (tie each swing to a real catalyst — news/macro/event, cited), a **fundamentals/what-is-it primer**, and a **strategies section** (DCA, hold, hedging, risk — educational, not advice). Progressive depth: beginner → intermediate. Reuses the events/news + OHLCV + research engines; the LLM narrates *grounded* explanations over real data (never invents catalysts). Ties into the agentic orchestration (E) as a `explain_asset` / `annotate_chart` tool. **Rule:** clearly labeled educational, disclaimers on strategies.

## E. Architecture — agentic orchestration (DECIDED: 3-layer hybrid)
- [ ] **E1 · P1 · L** — Formalize a **tool layer**: expose each capability as a typed tool (`get_portfolio`, `run_backtest`, `research_company`, `screen_stocks`, `analyze_balance_sheet`, `get_tax_summary`, …).
- [ ] **E2 · P1 · L** — Grow the **existing chat agent into the orchestrator** (NL request → pick + call tools → grounded cited answer). Make NL the primary interface (reduces the menu-maze).
- [ ] **E3 · P1 · M** — A few reasoning **sub-agents** where real reasoning is needed: Research/analyst (exists), Screening (NL→query), Portfolio-review, Balance-sheet-insights.
- [ ] **E4 · (rule)** — **NEVER agentize the money math** — marking/tax/backtest/XIRR stay deterministic, unit-tested services (the valuation bug is why). Agents *call* them; they don't *replace* them.

## F. Model / signals R&D (no demonstrated edge today)
- [ ] **F1 · P1 · S** — Demote Signals (below coin-flip, all HOLD). Keep honest label.
- [ ] **F2 · P1 · L** — Change the ML target: daily direction → **volatility / regime forecasting** (vol-cone exists) or **event-reaction**. More signal there.
- [ ] **F3 · P1 · M** — Fix **bear-regime data starvation** (models train on ~1k rows) — pool wider universe + longer history.
- [ ] **F4 · P1 · M** — Gate the **ML model through the backtest engine with costs** (economic value, not hit-rate) before surfacing it.

## G. Testing & misc
- [ ] **G1 · P1 · M** — **UI click-through testing of every page** (this session tested backend/data only — that's how the bell bug hid). Do a browser-driven pass.
- [x] **G2 · P2 · S** — Journal **delete** — **DONE**. `DELETE /journal/entries/{id}` (204) + per-card trash button w/ confirm + 2 tests.
- [ ] **G3 · P0 · S** — Commit the two audit docs to the repo so they're tracked.

---

## Suggested order for tomorrow
1. **Quick wins (a few hours):** A1 (bell), A3+A4 (backups/scheduler), B1+B2 (US/SEC keys), B3 (news keys) → fixes trust + un-empties features.
2. **Restructure (1–2 sessions):** C1–C6 → the clutter you're frustrated with.
3. **Then choose the big build:** D1 (broker import) or E1–E2 (orchestrator) or D3 (balance-sheet insights).

## Status snapshot (end of 2026-07-05)
- Deployed + live-verified: valuation consistency, peer comparison, backtest run, morning-brief AI, honest source-health, rich fundamentals. (Score 7.5/10 as a money tool.)
- Empty-pending-data: calibration, tax, harvest, themes (all correct, need real data/weekly run).
- Not started: everything in C, D, E, F above.
