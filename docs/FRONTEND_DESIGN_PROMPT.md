# Frontend redesign prompt for PFIP

Paste the entire block below (starting at `---` and ending at the final
`---`) into v0.dev / Lovable / Bolt.new / Google Stitch / Claude in
Chrome. Each of those tools handles long structured prompts well.

For best results: paste this once to set context, then iterate one page
at a time (`/dashboard`, `/portfolio`, etc.) — they all generate
better pages than they do full multi-page apps in one shot.

---

# PFIP — Personal Financial Intelligence Platform · UI redesign

## 1. What this product is

PFIP is a **single-user, self-hosted financial intelligence platform**
for someone managing their own money across crypto, US equities, Indian
equities, mutual funds, gold, and bonds. The user is a senior software
engineer who codes for a living — they want **information density and
keyboard speed, not friendly hand-holding**.

Think "personal Bloomberg terminal × Linear × Mercury Banking", not
"Robinhood × Mint".

Not a consumer fintech. Not a broker. Paper-trading only in v1; the
platform tells the user what its models think and what it would do, but
never executes trades. The user's brain is the kill switch.

## 2. Who uses it

- **One user.** No multi-tenant, no social, no sharing, no permissions
  matrix. Login is single bcrypt-hashed user.
- **Power user.** Comfortable with `Cmd+K`, dense tables, keyboard-only
  navigation, jargon-heavy labels. Does NOT need explainer tooltips on
  every term — they know what Sharpe means.
- **Read-mostly.** Most sessions are 30 seconds: open the dashboard,
  scan, close. Some sessions are deep dives — explore a signal, run a
  what-if, tag a journal entry.
- **Trust-sensitive.** Every number has a cited source. The UI never
  pretends to have data it doesn't (no "—", no "0" when the truth is
  "not yet ingested"). Empty states say *why* they're empty.

## 3. Design principles (non-negotiable)

1. **Information density first.** A KPI card is 2 lines of vertical
   space, not 6. A chart shares the row with 3 sibling charts on
   desktop. Generous whitespace is for the marketing site we don't have.
2. **Dark mode is the default.** Light mode is supported but ~80% of
   sessions are dark. Pick a neutral palette that works at 2am.
3. **Keyboard first.** `Cmd+K` palette opens everything. `g+d` goes
   to dashboard, `g+p` to portfolio, `g+w` to watchlist, `g+s` to
   signals, `g+j` to journal, `g+t` to tax, `g+x` to chat. `?` shows
   the shortcut sheet. Tables are arrow-key navigable.
4. **Numerical typography.** Every number uses tabular-nums + a mono
   numeric font (e.g. `font-feature-settings: "tnum"` + `font-variant-numeric:
   tabular-nums`) so they align visually. INR amounts with `₹` prefix,
   USD with `$`, BTC with the asset suffix.
5. **Source-of-truth always visible.** Every chart/card carries a tiny
   freshness dot (green/yellow/red) tied to the last successful ingest
   of the underlying source. Tooltip shows "updated 4m ago".
6. **No marketing tone anywhere.** No "Welcome back, Suresh!", no
   emojis on buttons (one or two specifically-chosen ones are OK in
   alert toasts and the welcome modal). Tone matches Linear / Vercel.
7. **Speed.** Initial paint < 1s. Every navigation is instant
   (skeleton → data swap). TanStack Query with 60s staleTime on most
   reads.
8. **Honest about uncertainty.** Confidence ranges, calibration scores,
   p-values are shown next to the prediction they qualify. "Buy with
   72% confidence" not "Buy".

## 4. Inspirations — borrow specifically from these

Reference each of these *by what to borrow*, not "make it look like X":

- **Linear** — left sidebar with collapsible sections; tiny breadcrumb
  in the top bar; pill-shaped status badges; `Cmd+K` modal; the entire
  feel of "an app for people who code".
- **Vercel Dashboard** — KPI strip with sparklines, deployment-style
  timeline component (we'll use this for signal history), graph card
  hover states.
- **Mercury Banking** — typography hierarchy on the account/portfolio
  page; balance-with-delta chip; the "minimal financial" aesthetic.
- **Stripe Dashboard** — table density and ergonomic filters/search;
  date-range picker; receipt-style transaction list (for our tax view).
- **Tremor / Tremor Blocks** — the actual KPI / area-chart / bar-list
  card components are great primitives to reuse.
- **TradingView** — charting depth & toolbar UX (we don't need their
  drawing tools, but the chart legend / timeframe pill / crosshair info
  panel is the bar).
- **Glassnode / Dune** — how they show on-chain metrics with primary +
  secondary axes + regime band shading in the background.
- **Notion** — the journal page (free-form entries with structured
  metadata) should feel like a Notion database with a custom layout.
- **Raycast** — the `Cmd+K` palette: result rows show icon + title +
  keyboard shortcut on the right; instant fuzzy filter; recent items.
- **Cron / Linear** — scheduling UX, calendar pickers; we have a tax
  calendar (advance-tax dates, NSE/NYSE holidays) that needs this.
- **Plaid Dashboard** — connection-status indicator pattern (we have
  ~50 ingest adapters; the Source Health page borrows this).
- **Sentry / Datadog** — alerting / incident timeline pattern; we mirror
  this for risk breaches and skipped tasks.

**Do NOT take inspiration from**: Robinhood (consumer-y, not enough
info density), Coinbase Pro (table-heavy without focus), Mint (cluttered,
broker-driven). Avoid neon-colored "trader" aesthetics — this is a
sober tool.

## 5. Tech stack (already in place — do not change)

- **Next.js 14** App Router, TypeScript strict.
- **Tailwind CSS** with shadcn/ui primitives (Card, Button, Input,
  Dialog, Table, Tabs, Toast, Tooltip, etc.).
- **Tremor** for KPI cards, sparklines, area/bar charts.
- **Recharts** for the more complex finance charts (candlesticks,
  multi-axis, regime-shaded backgrounds).
- **TanStack Query** for all server state. Mutations invalidate.
- **Lucide React** for icons. **No emoji icons in nav** — only Lucide.
- **next-auth** with credentials provider for single-user login.

Use these primitives. Don't introduce Material UI, Chakra, Mantine,
Bootstrap, or any other framework.

## 6. Color & typography tokens

Dark theme (primary):

- Background: near-black `#0a0a0b` with cards `#111114`, hover
  `#17171a`, borders `#1f1f23`.
- Text: primary `#e7e7ea`, secondary `#8b8b95`, muted `#54545c`.
- Accent (single brand color, used very sparingly): a deep teal
  `#14b8a6` for primary buttons + active nav item.
- Semantic:
  - Positive (green) `#10b981`
  - Negative (red) `#ef4444`
  - Warning (amber) `#f59e0b`
  - Info (blue) `#3b82f6`
- Regime band overlays (used behind charts at low opacity):
  bull `rgba(16, 185, 129, 0.06)`, bear `rgba(239, 68, 68, 0.06)`,
  sideways `rgba(245, 158, 11, 0.04)`, high-vol stripes.

Light theme (mirror): use Tailwind's neutrals, same accent.

Type:

- Sans: **Inter** at 13–14px base for UI, 12px for tables.
- Numeric: **JetBrains Mono** or **IBM Plex Mono** with tabular nums
  for every monetary, percentage, or ratio number.
- Headings: Inter, weight 600. H1 24px, H2 18px, H3 15px. Never more
  than two heading levels per page.

## 7. Information architecture — sidebar

Left sidebar, fixed 220px desktop, collapsible to icons. Sections:

1. **Workspace** (top, with user avatar + bcrypt-protected single
   account, no signup flow)
2. **Overview**
   - Dashboard (`/`)
   - What changed today (`/changes`)
3. **Markets**
   - Watchlist (`/watchlist`)
   - Signals (`/signals`)
   - Regime (`/regime`)
4. **Portfolio**
   - Holdings (`/portfolio`)
   - Risk (`/portfolio/risk`)
   - Allocation (`/portfolio/allocation`)
   - Shadow (`/portfolio/shadow`)
5. **Tax (India)**
   - Summary (`/tax`)
   - Schedule FA (`/tax/schedule-fa`)
   - Form 67 (`/tax/form-67`)
   - 80C optimizer (`/tax/80c`)
   - Loss harvesting (`/tax/harvest`)
6. **Tools**
   - Chat (`/chat`)
   - Journal (`/journal`)
   - Calibration (`/calibration`)
   - Backtest (`/backtest`)
7. **Operations**
   - Source health (`/ops/sources`)
   - Alerts (`/ops/alerts`)
   - Schedules (`/ops/schedules`)
   - Models (`/ops/models`)
8. **Settings** (`/settings`)

A second top-bar shows: search (`Cmd+K` opens a global palette),
network status dot, theme toggle, profile menu.

## 8. Page-by-page spec

### 8.1 Dashboard (`/`)

The 30-second-scan page. Layout: 12-column grid, generous breakpoints.

Top strip (full width, 4 KPI cards):
- **Net worth (INR)** with 1d / 7d / 30d delta chips, tiny 30d sparkline.
- **Today's P&L** signed, color-coded.
- **Drawdown from peak** with a thin progress bar vs the 20% halt threshold.
- **Active signals** count with a regime breakdown chip below.

Row 2 (2 columns):
- **BTC chart** (8 cols) — candlesticks, regime band shading, timeframe
  pills (15m / 1h / 4h / 1d), drawer for indicators (RSI, MACD).
- **Regime stack** (4 cols) — list of every tracked symbol with regime
  badge (bull / bear / sideways / high-vol) and a 30-day sparkline.

Row 3 (2 columns):
- **Watchlist movers** (6 cols) — top 3 gainers + top 3 losers table.
- **Risk snapshot** (6 cols) — drawdown vs halt threshold gauge, daily
  new-positions used vs cap, correlation cluster summary.

Row 4 (full width):
- **What changed today** — feed-style: new signals fired, regime flips,
  >5σ watchlist moves, top news clusters.

Row 5 (2 columns):
- **Top news** (6 cols) — 5 most-impactful news items in the last 24h
  with sentiment chip + source.
- **Recent journal entries** (6 cols) — last 5, with pre-trade checklist
  completion status.

Every card has a freshness dot in its title row.

Empty-state for the entire dashboard: a polite welcome modal with three
choices — Bootstrap real data, Seed demo data, Dismiss.

### 8.2 Watchlist (`/watchlist`)

Two-pane: left = filter sidebar (market: All / US / India / Crypto /
MF / FX), right = sortable table.

Columns: symbol, market, last price (native ccy), 24h % change with
sparkline, 7d %, 30d %, regime badge, signal count, last-updated dot,
actions (remove). Row click → asset detail drawer.

Add-symbol button → command-palette-style modal: type to search, group
results by market.

### 8.3 Signals (`/signals`)

Two views, toggle:
- **Card view** — each signal a card with: symbol header, BUY/SELL/HOLD
  pill, confidence bar (showing the 65 threshold), regime context,
  expandable "drivers" section showing top-5 SHAP features with signed
  bars, expandable "news" section showing top-5 supporting + top-3
  opposing items with sentiment chips, "open in chat" CTA.
- **Table view** — dense, sortable, filterable. Filters: regime, kind,
  confidence range, time range.

Top filters: regime, confidence floor slider, fired-since date picker.

### 8.4 Portfolio (`/portfolio`)

Header strip: total value INR + delta, exposure-by-asset-class
treemap (mini), unrealized P&L summary.

Main: holdings table. Columns: symbol, asset class, qty (tabular),
avg cost, current price, unrealized P&L (signed), realized YTD,
% of portfolio, days held, action menu.

Right sidebar: tabs for **Risk** (VaR 95/99, Sharpe, Sortino, Calmar,
correlation matrix heatmap, concentration Herfindahl), **Allocation**
(target vs actual stacked bars, rebalance suggestions), **Shadow**
(side-by-side: live vs shadow portfolio, deltas highlighted).

Import-CSV button at top right opens a wizard: choose broker (10
adapters: Zerodha, ICICIdirect, Groww, INDmoney, Vested, WazirX,
CoinDCX, Binance, Coinbase, Kraken), drop file, preview parsed rows,
confirm.

### 8.5 Tax (`/tax`) — Indian context

Hero card: current FY tax liability estimate (INR), with breakdown:
STCG equity (15%), LTCG equity (10% above ₹1L), VDA crypto (30%+1% TDS),
slab-rate items.

Tab strip: Summary · Schedule FA · Form 67 · 80C optimizer ·
Harvesting · Regime comparison · ITR JSON export.

Each tab is dense table + action buttons. Schedule FA is the most
complex — country, ISIN, peak balance USD + INR, dividends, proceeds.
Form 67 is the DTAA credit row by country with the min(foreign, indian)
calculation visible inline.

80C optimizer is a slider-and-ranked-list UI: drag the contribution
sliders (PPF / NPS / ELSS / etc.), see the projected tax saved.

Loss harvesting: ranked list of holdings whose loss could offset
existing realized gains, with estimated tax saved per suggestion.
**Crypto excluded** (Indian law). Warning chip on FY-end-adjacent
suggestions.

### 8.6 Chat (`/chat`)

Left: thread list (the user only has a few threads — "general", "tax",
"crypto"). Right: message stream with SSE streaming. Above the
composer: source-citation chips that appear when the agent grounds
its answer.

Special message types:
- Tool-call rendering (e.g. "fetched 14 holdings" with expandable
  table).
- Source citation footer block with book/chapter/page or news URL.
- Privacy badge: shows whether the prompt was routed to local Ollama
  (PERSONAL) or a cloud provider (PUBLIC/SENSITIVE).

### 8.7 Journal (`/journal`)

Card grid: each open trade is a card with symbol, direction, opened-on,
thesis snippet, invalidation line, conviction (1-10 chip). Closed
trades collapse into a "closed" filter.

"New entry" button opens the **10-item Appendix-B checklist modal**.
All 10 must tick green before save:
regime_check, risk_size_ok, thesis_written, exit_plan_defined,
invalidation_set, correlation_check, liquidity_check,
tax_impact_considered, news_check, regime_alignment, plus
conviction_score (1–10 slider).

Closing a trade opens the **post-mortem dialog** with an "Auto-draft
with agent" button (calls the LLM router) and a 5-section markdown
form: Thesis result / What worked / What didn't / Pattern tag /
Lesson for next time.

Header card: **Top failure patterns this month** (from the
`/journal/patterns` endpoint).

### 8.8 Calibration (`/calibration`)

Per-model card: name, version, reliability diagram (Recharts), Brier
score, ECE bar with the 0.15 suspension threshold marked. Sortable
table of models below with calibration deltas vs last month.

### 8.9 Backtest (`/backtest`)

Form to launch a walk-forward + CPCV + Monte Carlo backtest (symbol,
strategy, train window, step, embargo). Status panel shows running
flow. Results: an embedded QuantStats-style tearsheet with equity
curve, monthly returns table (year × month grid), drawdown series,
Sharpe / Sortino / Calmar / max-DD / CAGR / hit rate.

### 8.10 Operations · Source Health (`/ops/sources`)

Four KPI cards at top: total adapters, healthy, stale, failing.
Full table below: adapter name, status badge, last-run age, last
success age, rows, consecutive failures. Collapsible drawer with
last-error text per failing adapter. Auto-refresh every 60s.

### 8.11 Operations · Alerts (`/ops/alerts`)

Sentry-style timeline: each alert is a row with severity color stripe,
kind icon, title, body excerpt, timestamp, ack button. Filter by
severity / kind / time range.

### 8.12 Operations · Schedules (`/ops/schedules`)

Cron-style table: deployment name, cron expression, last run, next run,
last success, last duration, status. Trigger-now button per row.

### 8.13 Operations · Models (`/ops/models`)

Registry catalogue: model id, name, kind (pkl/onnx/HF), task, regime,
horizon, version, in-sample acc, SHA, created. Pin button per row.
Pinned model gets a star.

### 8.14 Settings (`/settings`)

Cards stacked: Risk limits (position cap, drawdown halt, correlation
cap, daily new-positions cap, Van Tharp R-size), Tax (FY, regime
preference, surcharge bracket), Alerts (severity routing, quiet hours,
rate cap, kill switch), LLM (provider priority, sensitivity defaults),
Source Health panel, Scheduled tasks list.

## 9. Component patterns to define once and reuse

- `<KpiCard label value delta sparkline href freshness />`
- `<FreshnessBadge sources={["coinbase_ohlcv", "fred_macro"]} />` —
  small dot + tooltip showing last-success age.
- `<RegimeBadge regime />` — colored pill: bull/bear/sideways/high-vol.
- `<ConfidenceBar value floor=65 />` — horizontal bar with 65 threshold.
- `<SignalCard signal />` — with collapsible drivers + news sections.
- `<CitationBlock sources />` — appended to grounded agent messages.
- `<CommandPalette />` — global `Cmd+K`. Action types: navigate, run
  query, ask agent, trigger flow.
- `<EmptyState title description action />` — for every page.
- `<DataTable />` — virtualized, keyboard-navigable, with sort + filter
  + multi-select.
- `<SourceHealthPanel />` — reusable on Settings + standalone page.

## 10. Realistic data shapes (mock these to match the real API)

```ts
type Signal = {
  id: string;
  symbol: string;          // "BTC/USD" or "RELIANCE.NS"
  direction: "BUY" | "SELL" | "HOLD";
  confidence: number;      // 0..100, threshold 65
  regime: "bull_trend" | "bear_trend" | "sideways" | "high_volatility" | "accumulation" | "distribution";
  generated_at: string;    // ISO 8601 UTC
  drivers: { feature: string; value: number; contribution: number }[];
  model: string;           // "lgbm_trend_specialist"
};

type Holding = {
  id: string;
  symbol: string;
  asset_class: "equity" | "equity_mf" | "debt_mf" | "vda" | "us_stock" | "gold";
  qty: number;
  avg_cost_inr: number;
  current_price_inr: number;
  first_acquired_on: string;
  source: "self_custody" | "exchange" | "broker" | "manual";
};

type JournalEntry = {
  id: string;
  symbol: string;
  direction: "BUY" | "SELL" | "HOLD";
  pre_trade: {
    thesis: string;
    invalidation: string;
    position_size_pct: number;
    time_horizon: string;
    conviction_score: number;
    correlation_check: boolean;
    liquidity_check: boolean;
    tax_impact_considered: boolean;
    news_check: boolean;
    regime_alignment: boolean;
    risk_size_ok: boolean;
    thesis_written: boolean;
    exit_plan_defined: boolean;
    invalidation_set: boolean;
    regime_check: boolean;
  };
  opened_at: string;
  closed_at: string | null;
  post_mortem: {
    outcome_pnl_inr: number;
    outcome_pnl_pct: number;
    thesis_correct: boolean;
    followed_plan: boolean;
    what_worked: string;
    what_didnt: string;
    lessons: string;
    next_actions: string;
  } | null;
};

type SourceHealth = {
  source: string;          // "coinbase_ohlcv"
  status: "healthy" | "stale" | "failing" | "never_run";
  last_run_at: string | null;
  last_success_at: string | null;
  last_rows: number | null;
  consecutive_failures: number;
  last_error: string | null;
};

type Alert = {
  id: string;
  kind: "morning_brief" | "regime_change" | "signal_fired" | "risk_breach" | "drawdown_halt" | "ingest_failure" | "calibration_breach" | "weekly_review" | "system_health";
  severity: "INFO" | "WARN" | "CRITICAL";
  title: string;
  body: string;
  sent_at: string;
  acked: boolean;
};
```

## 11. Edge cases — handle deliberately

- **Cold start** (no data ingested yet): every page shows a polite
  empty state with one of three CTAs: "Bootstrap real data" /
  "Seed demo data" / "Read the docs". The dashboard auto-opens the
  welcome modal.
- **Stale data**: freshness badges go yellow (>1× expected cadence)
  then red (>2×). A toast appears on first load if anything is red.
- **Failing adapter**: red dot + Source Health page lists with the
  last error text + a runbook link.
- **LLM unavailable**: chat composer shows a banner "LLM router
  down — falling back to local Ollama. Latency may be higher."
- **Pre-trade checklist incomplete**: save button disabled with the
  failing items highlighted.
- **Drawdown halt fired**: dashboard hero shows a red banner across
  the top; risk snapshot card gets a red border; alert center pops up.

## 12. Mobile (narrow viewport ~390px)

- Sidebar collapses to a bottom-tab nav with 5 icons (Dashboard,
  Portfolio, Signals, Chat, More).
- KPI strip stacks vertically.
- Charts get a horizontal scroll wrapper.
- Tables collapse to card-per-row.
- The journal new-entry dialog becomes a full-screen sheet.
- `Cmd+K` becomes a search icon in the top bar.

## 13. Accessibility

- Every interactive element keyboard-navigable.
- Color is never the only indicator (positive uses +, negative uses −).
- Focus rings visible (Tailwind `focus-visible:ring-2`).
- Tables have proper `<th>` headers + ARIA sort attributes.
- Color contrast WCAG AA (the palette above passes).
- Reduced-motion respected for sparkline transitions.

## 14. Anti-patterns to avoid

- **No giant hero sections** with marketing copy.
- **No "Welcome back" greeting** — never address the user.
- **No emoji in nav or buttons** (alerts and toasts only).
- **No dropdowns more than 2 levels deep**.
- **No modal that locks the page** — always escapable with ESC.
- **No loading spinners** longer than 200ms — show skeletons instead.
- **No "trader green/red"** neon colors — use the muted semantic palette.
- **No tooltips on hover for primary content** — content should stand
  alone; tooltips are for affordances only.
- **No fixed widths** — every layout flexes from 360px to 2560px.

## 15. Build order suggestion (if iterating)

1. Sidebar + top-bar shell + theme tokens + `Cmd+K` palette.
2. Dashboard (`/`) — the 30-second-scan page is the highest-impact
   surface.
3. Portfolio (`/portfolio`) — daily check.
4. Signals (`/signals`) — the model surface.
5. Tax (`/tax`) — the seasonal heavy hitter.
6. Journal (`/journal`) — the discipline tool.
7. Operations pages — the trust layer.
8. Chat (`/chat`) — last because it depends on streaming infra.

---

End of prompt. Ship dark mode by default. Match the information density
of Linear, the typography hierarchy of Mercury, and the chart depth of
TradingView. Every number cites its source.
