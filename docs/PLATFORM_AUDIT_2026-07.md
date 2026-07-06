# PFIP — Full Platform Audit (solo-hedge-fund lens)

*Date: 2026-07-05. Method: code read of every router + page, two live end-to-end
evaluations against the deployed app, and per-feature validation of the data
source and flow. Framing: would this pass as a **solo hedge-fund cockpit** —
trustworthy numbers, a tight decision workflow, no dead weight.*

**Overall verdict: 6.5 / 10 as a product; 8/10 as an engine.** The analytical
core (valuation, research, fundamentals, backtest) is real and now trustworthy.
It loses points on: (a) US data staleness, (b) a **model layer with no edge that
is presented as if it has one**, (c) **~10 half-finished or redundant features**
that bloat the UI, and (d) small broken UX (the notification bell). Fix those and
it's a genuine 8.5.

---

## 1. Feature-by-feature audit (pin-to-pin)

Legend — **Works:** Pass / Partial / Fail · **Keep:** Keep / Merge / Demote / Cut

| # | Feature | Data source & flow | Works | Correct? | Keep | Notes / bug |
|---|---|---|---|---|---|---|
| 1 | Dashboard `/` | OHLCV candles + regime + changes-today + morning brief | Partial | Yes for fresh classes | Keep | US chart stale (9.7d); one-glance is good but crowded |
| 2 | Watchlist `/watchlist` | `watchlist` table + latest OHLCV | Pass | Yes | Keep | US/metal ETFs price null when US feed stale |
| 3 | Signals `/signals` | LGBM (regime-routed) over 5 technicals → t+3 direction | **Fail (no edge)** | **Mechanically yes, predictively no** | **Demote** | 16 signals, **all HOLD, avg conf 9.8%**; OOS hit ~0.46 (< coin flip). See §4 |
| 4 | Events `/events` | news → keyword catalyst extractor → `events` table | Partial | Yes (advisory) | Merge→Research | Thin (news corpus sparse); entity-link fixed |
| 5 | Themes `/themes` | news exposure over watchlist → ranked beneficiaries | Partial | Yes | Merge→Research | Empty when news thin (matched_stories 0) |
| 6 | Research (Diligence) `/diligence` | screener/finnhub + FII/DII + regime + news | Pass | Yes | **Merge** | Duplicate of #7 in users' eyes |
| 7 | Deep Research `/research` | LLM name→ticker → live fundamentals + 5-yr statements + peers + dossier | **Pass ⭐** | Yes, cited, no hallucination | **Merge (as primary)** | Flagship; #6 should fold into this |
| 8 | Holdings `/portfolio` | holdings + canonical marking | Pass | **Yes (now consistent)** | Keep | Paper-seed data; real import missing (§6) |
| 9 | Net worth `/net-worth` | marking + FX + illiquid at cost | Pass | Yes | **→ Portfolio tab** | Timeline clip fixed |
| 10 | Benchmark `/benchmark` | portfolio value path vs ETF proxy | Pass | Yes (Max fixed) | **→ Portfolio tab** | |
| 11 | What-if `/what-if` | simulate trade vs marked book | Pass | Yes (valuation_note added) | **→ Portfolio tab** | |
| 12 | Stress test `/stress-test` | scenario shocks on marked book | Pass | Yes (marking added) | **→ Portfolio tab** | |
| 13 | Shadow `/shadow` | paper-model mirror vs actual | Partial | Yes (return fixed) | **Demote→Lab** | Niche; depends on signals having value |
| 14 | Tax `/tax` | FIFO capital gains, STCG/LTCG, ITR, PDF | Pass | Yes | Keep | Empty until real realized lots (no import) |
| 15 | Loss harvesting `/tax/harvest` | open lots vs marks, 115BBH rules | Pass | Yes (lot mapping fixed) | **→ Tax tab** | Shows skipped reasons now |
| 16 | Goals `/goals` | Monte-Carlo corpus projection | Pass | Yes | Keep | Genuinely useful |
| 17 | SIP `/sip` | XIRR + corpus projection | Pass | Yes | **→ merge with Goals ("Plan")** | |
| 18 | Journal `/journal` | decision log + auto post-mortem draft | Pass | Yes | Keep | No delete endpoint (minor) |
| 19 | Chat `/chat` | SSE agent graph, RAG + DB grounding | Pass | Yes (grounding improved) | Keep | Now quotes in-DB prices |
| 20 | Perspectives `/perspectives` | 3 LLM personas in parallel | Pass | Yes | **Merge→Chat** | A mode of Chat, not its own page |
| 21 | Calibration `/calibration` | ECE/Brier of resolved signals | **Fail (empty)** | Yes (but data-gated) | **→Lab** | 0 reports: model makes ~no directional calls |
| 22 | Backtest `/backtest` | walk-forward+CPCV of rule strategies | Pass | Yes (500 fixed) | **→Lab** | Rule strategies only, not the ML model |
| 23 | Source health `/ops/sources` | source_health + freshness + keyed | Pass | Yes (now honest) | **→Lab** | Great diagnostic; not user-facing |
| 24 | Schedules `/ops/schedules` | systemd timer status | Partial | Yes | **→Lab** | Backup/weekly timers never ran |
| 25 | Models `/ops/models` | model registry + metrics | Pass | Yes | **→Lab** | Shows the no-edge OOS honestly |
| 26 | Settings `/settings` | prefs + self-custody + source health | Pass | Yes | Keep | |
| 27 | Notifications (bell) | `/notifications/recent` | **Fail (bug)** | No | Fix | **Renders only the count, discards `items`; stale "when backend wires the endpoint" copy.** Backend returns full list — frontend ignores it. |
| 28 | Morning brief | LLM over portfolio+news+regime | Pass | Yes (LLM works now) | Keep | Surface on Dashboard |
| 29 | Self-custody wallets | mempool/etherscan/solscan | Partial | Yes (on-add sync added) | Keep | On-chain balance folds into net worth |
| 30 | Alerts engine | source-health + signal → notifications | Partial | Yes | Keep | No user-defined price alerts (§6) |

**Headline bugs found (beyond the two evals):**
1. **Notification bell is broken** — shows a badge count but the dropdown never lists the actual notifications; tells you to "see Telegram." The `/notifications/recent` payload has full `items`; the frontend reads only `unread`. **Confirmed, needs a ~20-line frontend fix.**
2. **Signals presented as actionable** — placed in "Markets" with confidence numbers, but every call is HOLD at ~9.8% confidence and the model is below coin-flip. Misleads.
3. **Backup + weekly schedulers never ran** — no DB backups exist; calibration/diligence starve. (GitHub crons `startup_failure`; VM timers `last_run: null`.)
4. **US data keys missing on the VM** — Tiingo/Finnhub/Alpha-Vantage read `NO-KEY` in the ingest env → US prices/fundamentals/statements don't refresh.

---

## 2. Data reliability — current state & better sources

| Class | Now | Trust | If not good enough → better source |
|---|---|---|---|
| Crypto px | Bybit/CCXT, 0.7d | ✅ | Fine; add CoinGecko Pro for breadth |
| India equity px | jugaad/NSE bhavcopy, 3.7d | ✅ | Fine; **Kite Connect** (Zerodha) if you have a broker acct |
| India fundamentals | screener.in scrape | ✅ (top ratios) | **Tickertape/Trendlyne API** or Kite for full statements |
| US equity px | Tiingo→yf→stooq, **9.7d STALE** | ❌ | **Fix the key first.** Reliable paid-lite: **Tiingo** (works) / **Polygon.io** / **Financial Modeling Prep (FMP)** |
| US fundamentals | Finnhub / Alpha Vantage | ⚠️ key-gated | **FMP** (250/day free, full statements) beats AV's 25/day |
| Statements (5-yr) | Alpha Vantage | ⚠️ 25/day | **FMP** — much higher limit, cleaner statements |
| Macro | FRED | ✅ (fixed) | Fine |
| MF NAV | AMFI | ✅ (fixed) | Fine |
| News/events | RSS/GDELT/Reddit + AV | ⚠️ **thin** | **This is the weak link.** Add **Marketaux / NewsData / Benzinga**; it starves Events, Themes, per-name filings |
| FX | Frankfurter | ✅ | Fine |
| On-chain | mempool/etherscan/solscan | ✅ | Fine |

**Reliability verdict:** *India-first is trustworthy today; US and news are the two
weak axes.* Both are **config/keys + one nightly run**, not architecture. The
single best data investment is **swapping US fundamentals/statements to FMP** and
**adding a real news provider** — those two unlock the most currently-empty
features (statements, themes, events, filings).

---

## 3. Overall flow validation (does each pipeline do what it claims?)

- **Ingest → features → regime → signals → store** ✅ mechanically sound; guarded, health-recorded, freshness-checked. The *inputs* (US px, news) are the weak part, not the plumbing.
- **Valuation flow** ✅ now single-source (one FX-aware marking feeds summary/stress/shadow/what-if/net-worth). Verified equal live.
- **Research flow** ✅ name→ticker→live fundamentals→statements→peers→cited LLM dossier; refuses to fabricate. Best flow in the app.
- **Signals flow** ⚠️ correct *code*, wrong *premise* — see §4.
- **Alerts flow** ⚠️ source-health + signals → notifications works server-side, but the **bell doesn't render it** and there are **no user-defined alerts**.

---

## 4. Signals & models — the honest read

**What it uses:** per-regime **LightGBM** classifiers over ~5 technical features
(`rsi_14, macd_hist, atr_14, return_7d, volatility_30d`), routed by an HMM regime
label, predicting **t+3 up/down**. Isotonic-calibrated, confidence floor 65.

**How it performs (live registry):**

| Regime | OOS hit-rate | Train rows |
|---|---|---|
| bull_trend | 0.41 / 0.42 / 0.53 | 11k–18k |
| bear_trend | 0.50 / 0.48 / 0.42 | **1k–5k (thin!)** |
| sideways | 0.45 / 0.46 / 0.49 | 33k–41k |

**Average ≈ 0.46 — below a coin flip.** Live signals: **all HOLD, avg confidence
9.8%.** Calibration can't populate because there are ~no directional calls. The
only positive backtest (BTC MA-cross Sharpe 1.07) is a **rule** strategy, not the
model.

**Verdict:** the ML layer has **no demonstrated edge** and should not sit in the
main nav as if it does. **Improvements, in order:**
1. **Demote Signals to "Lab"**, keep the "no proven edge" label — honesty is the feature.
2. **Change the target** — daily direction is the hardest bet. Move to **volatility/regime forecasting** (you have a vol-cone already) or **event-reaction** modelling; both have more signal.
3. **Fix bear-regime starvation** — 1k rows can't train a model; pool across a much wider symbol universe & longer history.
4. **Judge on economic value, not hit-rate** — wire the ML model (not just rule strategies) through the backtest engine with costs, and only surface it if net-of-cost Sharpe clears a bar.

**How the pros do it (comparison):** Danelfin/Boosted.ai publish *decile
performance + turnover + factor exposure*, not a single confidence number;
Composer/QuantConnect force *walk-forward + cost-aware* evaluation before a
strategy goes live. PFIP has the *machinery* (CPCV, embargo, shuffle-test) but
doesn't gate the model behind it. Adopt that gate.

---

## 5. Competitive comparison (per capability — how others do it, where we lag)

| Capability | Best-in-class | How they do it | PFIP gap |
|---|---|---|---|
| **Portfolio aggregation** | Kubera, Sharesight, Empower | Auto-sync brokers/banks/wallets; corporate actions; multi-currency | **No broker/exchange sync** — manual entry only (biggest gap) |
| **Company research** | Koyfin, Tickertape, Simply Wall St, Finchat | Full statements, peer tables, visual health, analyst estimates | We have peers+5-yr now; **missing estimates, segment data, visual "snowflake"** |
| **Screener** | Tickertape, Screener.in, Finviz | Filter universe by any ratio; save screens | **No screener at all** — we ingest the data but can't query it |
| **Charting** | TradingView | Intraday, indicators, drawing | **Daily-only, no indicators/intraday** (by design, but limiting) |
| **Backtesting** | Composer, Portfolio Visualizer, QuantConnect | Visual strategy builder, cost model, MC | We have a rigorous engine but **only 3 canned strategies, no builder** |
| **AI research** | BloombergGPT, Finchat, Danelfin | Grounded, cited, tool-using | **Deep Research is competitive here** ✅ (our strongest vs-market feature) |
| **Alerts** | TradingView, Kubera | User price/%/indicator alerts → push/mobile/email | **No user alerts, bell broken, no push** |
| **Tax (India)** | Quicko, ClearTax, Zerodha Console | Broker-synced P&L, auto ITR | Engine is solid but **no broker P&L import** → stays empty |
| **News/catalysts** | Benzinga, Koyfin, Tickertape | Deep, entity-tagged, real-time | **Thin corpus** — the limiting input |
| **Mobile** | Every competitor | Native or PWA + push | **None** — desktop web only |

**Where we genuinely win:** grounded, cited **Deep Research over any name with
India-first fundamentals** — Koyfin/Simply Wall St don't do India well, and the
"refuses to fabricate" honesty is rare. That's the moat. Everything else is at or
behind market.

---

## 6. Missing features a solo hedge fund actually needs (P0→P2)

- **P0 — Broker/exchange auto-import** (Zerodha Kite, Binance, ICICIdirect). Unlocks real Holdings, Tax, XIRR, Harvest (all currently empty of real data).
- **P0 — Fix US data + news keys** (config). Unlocks US freshness + statements + themes + events.
- **P0 — Working notification bell + user-defined alerts** (price/%/threshold/catalyst → in-app + Telegram + email). Half the plumbing exists.
- **P1 — Screener** over the fundamentals you already store ("ROCE>20 & P/E<25 & D/E<0.5").
- **P1 — Analyst estimates / forward numbers** in Research (FMP/Tickertape).
- **P1 — Corporate-actions & earnings calendar** (real, per-holding).
- **P2 — Mobile PWA + web push.**
- **P2 — Options/F&O (India)** payoff + greeks.

## 7. Useless / redundant — cut or merge

- **Perspectives** → a *mode* inside Chat, not a page.
- **Research vs Deep Research** → one page.
- **Net-worth / Benchmark / What-if / Stress / Shadow** → **tabs under Portfolio**, not 5 menu items.
- **Signals / Calibration / Backtest / Source health / Schedules / Models** → a single **"Lab"** section for power users, collapsed by default.
- **Shadow** → only meaningful once signals have value; demote.

## 8. Proposed information architecture (25 items → 5)

```
Home            → dashboard + your portfolio + morning brief + alerts
Research        → Search (dossier) · Events · Themes · Ask AI (chat+perspectives)
Portfolio       → Holdings · Net worth · Benchmark · What-if · Stress · Shadow · Tax
Plan            → Goals · SIP · Journal · Watchlist
Lab (advanced)  → Signals* · Backtest · Calibration · Models · Source health · Schedules
Settings
        (* labeled "experimental — no proven edge")
```
Everyday users touch 4 things; the model/ops machinery is one click into "Lab".

---

## 9. Prioritized roadmap

| Pri | Item | Type | Effort |
|---|---|---|---|
| **P0** | US + news data keys on the VM | config | 5 min |
| **P0** | Fix notification bell (render items) + stale copy | frontend | ~1 hr |
| **P0** | IA restructure (25→5, merge research, Portfolio tabs, Lab) | frontend | 1–2 sessions |
| **P0** | Enable backup timer (no backups today) | infra | 5 min |
| **P1** | Broker/exchange import (Kite/Binance) | backend | multi-session |
| **P1** | User-defined alerts + delivery | full-stack | 1–2 sessions |
| **P1** | Screener over stored fundamentals | full-stack | 1 session |
| **P1** | Swap US fundamentals/statements → FMP | backend | 1 session |
| **P1** | Model pivot (vol/regime target, fix bear data, cost-gated) | R&D | multi-session |
| **P2** | Estimates, earnings calendar, mobile PWA, options | mixed | later |

**If I could do only three things:** (1) fix the US/news keys, (2) restructure the
nav + fix the bell, (3) broker import. Those three move it from "impressive engine,
cluttered app" to "a solo hedge-fund cockpit I'd run daily."
