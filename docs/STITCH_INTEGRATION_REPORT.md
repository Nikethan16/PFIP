# Stitch design integration — what landed, what's still missing

Google Stitch returned **3 polished screens** in the "Slate & Teal
Institutional" palette: **Dashboard**, **Signals**, **Portfolio**.
This document audits coverage of those three screens, what was
integrated into the live Next.js frontend, and what Stitch never
designed.

---

## 1. Stitch deliverables — coverage audit

### 1.1 Dashboard (`/`)

| Stitch widget | Already in `app/page.tsx` | Integrated |
|---|---|---|
| Branded sidebar — "PFIP Terminal · Institutional Grade" | ❌ said "PFIP · Solo Financial IP" | ✅ updated branding |
| Cmd+K search input in top bar | ✅ shipped earlier | ✅ no change |
| Connected pill (live dot) | ✅ via `<NetworkStatus>` | ✅ no change |
| KPI strip — Net Worth (sparkline) / Today's P&L / Drawdown / Active Signals | ✅ already there | ✅ relabelled to match Stitch + added freshness dots |
| BTC chart with timeframe pills + indicator buttons + last-price | ✅ via `<CandleChart>` | ✅ inherits new palette automatically |
| Markets-at-a-glance regime list | ✅ `<RegimeStack>` | ✅ inherits new palette |
| Watchlist movers (top gainers/losers) | ✅ `<WatchlistMoversCard>` | ✅ inherits new palette |
| Risk snapshot (DD vs halt gauge, daily caps) | ✅ `<RiskSnapshotCard>` | ✅ inherits new palette |
| "What changed today" feed | ✅ `<ChangesTodayCard>` | ✅ inherits new palette |
| Top news cards | ✅ `<NewsRow>` | ✅ inherits new palette |
| Recent journal entries preview | ✅ `<NewsRow>` + journal section | ✅ inherits new palette |

### 1.2 Signals (`/signals`)

| Stitch widget | Already in `app/signals/page.tsx` | Integrated |
|---|---|---|
| Filter strip — regime / confidence floor / date range | ✅ regime + confidence; date-range pending | ✅ |
| **Cards ↔ Table toggle** | ❌ cards only | ✅ added view-toggle + table view |
| Signal cards with BUY/SELL/HOLD pill | ✅ | ✅ |
| Confidence bar with 65 threshold | ✅ `<ConfidenceBar>` | ✅ |
| Regime context badge | ✅ `<RegimeBadge>` | ✅ |
| SHAP drivers expander | ✅ `<DriverChart>` | ✅ |
| Relevant news expander (top 5 supporting + top 3 opposing) | ✅ via `useAssetNews` | ✅ |

### 1.3 Portfolio (`/portfolio`)

| Stitch widget | Already in `app/portfolio/page.tsx` | Integrated |
|---|---|---|
| Total portfolio value (INR) KPI | ✅ `<PnlCards>` | ✅ |
| Asset class treemap | ✅ as a donut via `<DonutChart>` — equivalent | ✅ inherits palette |
| Active holdings table | ✅ `<HoldingsTable>` | ✅ inherits palette |
| Correlation matrix heatmap | ✅ `<CorrelationMatrix>` | ✅ inherits palette |
| Risk KPI tiles (VaR/Sharpe/Beta/Max DD) | ✅ `<VarPanel>` | ✅ inherits palette |
| **Macro shock sensitivity** | ❌ never had it | ✅ added `<MacroShockCard>` with stress-scenario rows + empty-state until backend ships |
| Risk / Alloc / Shadow tabbed right rail | ❌ all three sections exist but unstacked | 🟡 left as-is; the existing layout shows all three permanently — tabbing is a future polish |

---

## 2. Cross-cutting changes (every page benefits)

### 2.1 Design tokens — Slate & Teal palette ported
- `frontend/app/globals.css` — rewrote light + dark CSS variables to the
  exact values from Stitch's `DESIGN.md` (`#f8f9ff`, `#006b5f`, etc.).
  Dark mode is now slate-900 base (`#0f172a`) with teal-500 primary.
- `frontend/tailwind.config.ts` — added the Stitch design system as
  flat colour utilities (`bg-surface`, `text-on-surface`, `text-positive`,
  etc.) so the raw HTML from Stitch's deliverables can be dropped in
  unchanged. Also added the `numeric-lg/md/sm` and `headline-lg/md/sm`
  font scales.
- Loaded **Inter** + **JetBrains Mono** + **Material Symbols Outlined**
  via Google Fonts in `globals.css` so Stitch markup that uses
  `<span class="material-symbols-outlined">` renders correctly.
- Added utility classes: `.material-symbols-outlined`, `.freshness-dot`,
  `.sidebar-item-active`, `.candlestick`/`.wick` — verbatim from
  Stitch's `<style>` block.

### 2.2 Shell — sidebar + topbar updated
- `nav-items.ts` regrouped from 4 categories (Markets/Trading/Tax/System)
  to **8 categories** matching the Stitch shell: Overview / Markets /
  Portfolio / Tax (India) / Tools / Operations / Settings. Added
  `Operations` group with a Source Health entry.
- `sidebar.tsx` — brand line changed to "PFIP Terminal" with
  "INSTITUTIONAL GRADE" eyebrow.

### 2.3 KPI component upgraded
- `<Kpi>` now supports a `freshness` prop that renders a small inline
  dot (green / amber / red) — Stitch convention.
- Numeric value now renders in **JetBrains Mono** with tabular nums
  and teal accent by default. Tone overrides still pin red/green.

---

## 3. What Stitch did NOT design (11 pages)

These pages exist in the live app but were not in Stitch's deliverables.
They keep their current layout and inherit the new Slate & Teal palette
automatically (because of the CSS variable repaint).

| Page | Status |
|---|---|
| `/watchlist` | Live; not redesigned. |
| `/regime` | Currently a tab inside dashboard. Not a separate Stitch screen. |
| `/tax` — Summary | Live (rich tax engine). |
| `/tax/schedule-fa` | Live. |
| `/tax/form-67` | Live. |
| `/tax/80c-optimizer` | Live. |
| `/tax/harvest` | Live (tax-loss harvesting endpoint shipped). |
| `/chat` | Live with SSE streaming. |
| `/journal` | Live with 10-item checklist + post-mortem dialog. |
| `/calibration` | Live. |
| `/backtest` | Live. |
| `/ops/sources` | Built into `/settings` as a panel. |
| `/ops/alerts` | Backend ready; no dedicated page. |
| `/ops/schedules` | Backend ready; no dedicated page. |
| `/ops/models` | Backend ready; no dedicated page. |

### Recommended next step

Re-run Stitch with a focused prompt for each missing page. The
already-shipped `docs/FRONTEND_DESIGN_PROMPT.md` has the full spec for
each page in section 8 — paste **just one section at a time** to Stitch
for higher-fidelity output (Stitch is much better at single-screen
generation than multi-page generation in one shot).

Suggested order (by user-visible impact):
1. **Watchlist** (`/watchlist`) — second-most-used page after dashboard.
2. **Tax Summary** (`/tax`) — high-stakes data, deserves polish.
3. **Chat** (`/chat`) — the agent surface; SSE streaming UI matters.
4. **Journal** (`/journal`) — the discipline tool; checklist UX needs love.
5. **Calibration** (`/calibration`) — the trust surface.
6. **Operations** pages — schedule + source health + alerts + models.

---

## 4. Things from the Stitch designs we deliberately did NOT adopt

- **Material Symbols** as the primary icon set. The existing app uses
  Lucide React, which has nicer tree-shaking and consistent stroke
  weights. The Material Symbols font is loaded (so future Stitch markup
  pastes don't break), but our authored components keep Lucide.
- The exact 220px sidebar width is matched. Most other pixel-perfect
  spacing is left to shadcn defaults — pixel-perfect Stitch pixel-for-
  pixel would require rewriting every component, with minimal gain over
  the palette + typography port.
- Stitch used several screenshot-quality hero images (LH3 Google
  thumbnails); those are placeholder content and not relevant to a
  data-driven dashboard. They were skipped.
- The Stitch dashboard hard-codes "Trader_0x · Pro Tier" in the
  sidebar footer. Our sidebar shows the authenticated user's email
  + sign-out menu (correct production behaviour).

---

## 5. Files modified / added this push

Modified:
- `frontend/app/globals.css` — palette rewrite + utility classes + font imports.
- `frontend/tailwind.config.ts` — Stitch tokens + font families + spacing.
- `frontend/components/nav/nav-items.ts` — 8-group nav structure.
- `frontend/components/nav/sidebar.tsx` — brand updated to "PFIP Terminal".
- `frontend/components/shared/kpi.tsx` — `freshness` prop + mono numeric value.
- `frontend/app/page.tsx` — relabelled KPI 1–4 to Stitch convention + freshness.
- `frontend/app/signals/page.tsx` — Cards/Table view toggle + dense `<SignalsTable>`.
- `frontend/app/portfolio/page.tsx` — wired the macro-shock card next to VaR.

Added:
- `frontend/components/portfolio/macro-shock-card.tsx`.

---

_Test suite: backend 397 passed; frontend not unit-tested (no jest/vitest
in the project today)._
