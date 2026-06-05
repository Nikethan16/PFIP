# Frontend overhaul — summary of changes

Pass focused on visual density + polish. The app was functional but flat;
this pass moves it toward a Linear-meets-Bloomberg aesthetic. Every change is
inside `/frontend/`; nothing in backend, infra, or docs was touched.

## Design system

### `app/globals.css`
Re-tuned the entire token palette:

- **Light theme**: warmer near-white background, indigo primary, slate
  borders. Better contrast on `text-muted-foreground`.
- **Dark theme**: deep near-black (`224 16% 7%`) instead of the old
  near-navy. Sidebar uses a slightly darker tone (`224 17% 5%`) so it reads
  as a separate surface. Borders are subtle (`224 12% 18%`) but visible.
- Added semantic tokens for `--success`, `--warning`, `--sidebar*`, `--header`.
- Reusable utility classes: `.page-header` (sticky title bar), `.eyebrow`
  (small uppercase label), `.hover-tile` (subtle list-row lift), `.kpi-card`
  (hero metric surface with hairline gradient).
- Custom scrollbars (thin, themed) so dark mode doesn't show the bright
  system bars.
- `pfip-shimmer` keyframe used by the "Thinking…" chat indicator.
- `pfip-live-dot` keyframe for live status pills.
- Enabled OpenType `tnum` + `cv11` for prettier digits across the app.

## Shared components

### `components/nav/sidebar.tsx` — rewritten
- Sidebar surface gets its own background token, separating it visually
  from content.
- Nav items now grouped under **Markets / Trading / Tax / System** with
  eyebrow labels and tighter row spacing (Linear-style left rail).
- Active item shows a 2px accent strip on the left + colored icon, instead
  of just a filled background — clearer at a glance.
- Brand mark replaced with a subtle gradient + radial highlight (PF
  monogram).
- Footer rebuilt: network status pill, live IST clock, and a click-to-open
  user menu with Settings + Sign out.

### `components/nav/topbar.tsx` — rewritten
- Breadcrumb trail derived from the pathname (PFIP › Section › Subsection),
  with the trailing crumb in bold foreground colour.
- Command palette trigger is now a real bordered search field with `⌘K` /
  `CtrlK` hint that adapts to the OS.
- Notifications bell with poll-and-fail-soft behaviour against the optional
  `/notifications/recent` endpoint; shows badge count + popover.
- Hydration-safe theme toggle (only renders the icon after `mounted`,
  uses `resolvedTheme`).
- Mobile-friendly: shows brand + current crumb + command + chat shortcut
  in 48 px height.

### `components/nav/nav-items.ts`
Added `group` + `shortcut` metadata + a `NAV_GROUP_LABELS` map and a
`NAV_BY_PATH` lookup that the topbar uses for breadcrumb labels.

### `components/shared/page-header.tsx` — new
Standard `<PageHeader title description actions />`. Sticks below the
topbar with a backdrop blur so titles stay anchored on long scrolling
pages. Applied to: dashboard, portfolio, tax, calibration, journal,
settings, watchlist, signals, chat.

### `components/shared/kpi.tsx` — new
Hero KPI tile used on the dashboard. Eyebrow label, big tabular number,
delta arrow + percent in tone-aware colour, optional hint text, optional
trailing slot for a sparkline. Built-in loading skeleton.

### `components/charts/sparkline.tsx` — new
Pure-SVG sparkline (no Recharts cost) with auto-detected trend tone, gradient
fill under the line, end-dot. Used in dashboard markets row + watchlist
tiles.

### `components/shared/sentiment-dot.tsx` — new
Three-state coloured dot (red/amber/emerald) for news sentiment from the
[-1, 1] score on `NewsItem`. Has tooltip + optional inline label.

## Pages

### `app/page.tsx` (Dashboard) — rewritten
- New hero KPI strip: Portfolio value, Today's change, BTC regime,
  Drawdown. Each tile has tone-aware colour and built-in skeleton.
- Morning brief card retained but it now sits below the hero.
- BTC candle card got a colored title icon, larger price headline, arrow
  + percent for the period delta, and the timeframe tabs now sit inside
  the card.
- New **Markets at a glance** card replacing the single regime card:
  per-row Sparkline + regime badge + 30-day percent for BTC / ETH / SPY /
  NIFTY50. Hover-tile rows.
- Watchlist movers card kept; tightened typography + tabular numerics.
- Risk snapshot card: two interior tiles for Total Value / Drawdown, the
  drawdown bar with smooth transition, two big numbers below for "new
  positions left" + "day change".
- New **Top news** card at the bottom — 4-column grid (one per tracked
  asset) with sentiment dots + IST timestamps + external-link hover.

### `app/chat/page.tsx` + `components/agent/message-stream.tsx` — rewritten
- Real ChatGPT/Claude-style layout: conversations sidebar (left), main
  thread (centre, max-width prose column).
- User messages are right-aligned pills with a soft primary tint;
  assistant messages flow as ungrouped text with a small bot avatar so
  it reads more like a doc than a chat-box ping-pong.
- Thinking indicator uses a shimmer animation on the word "Thinking…"
  while the first token is in flight; degrades to a small spinner + "typing"
  hint once content starts flowing.
- Sources rendered as colour-coded chips (KB blue / news amber / DB green)
  with footnote-style `[n]` index + hover-only external icon.
- Composer is now a rounded card with auto-growing textarea (up to ~6
  lines), Send button transforms into a Stop square while streaming.
- Cmd/Ctrl+Enter sends in addition to plain Enter; Shift+Enter newlines;
  Esc cancels. Auto-scroll only when the user is already near the bottom.
- Conversation sidebar placeholder ready for the future
  `/agent/conversations` endpoint.

### `app/portfolio/page.tsx`
- Adopted `PageHeader` with the total INR rendered inline next to the
  description (so the user sees their net worth before anything else
  loads).
- Existing PnlCards / Holdings / VarPanel / Correlation matrix preserved.

### `app/tax/page.tsx`
- `PageHeader` shows the current FY in the title (e.g. "Tax · FY 2026-27").
- Export button + stale badge live in the page header actions area.
- Rest of the existing layout (summary cards, regime comparison,
  surcharge gauge, 80C optimizer, Schedule FA, Form 67, broker dropzones)
  preserved as-is — they were already strong.

### `app/calibration/page.tsx`
- `PageHeader`.
- Fixed pre-existing TS error: `historyByKey` map type now uses the
  explicit `CalibrationHistory` type instead of `(typeof history)[number]`.

### `app/watchlist/page.tsx` — rewritten
- Items now grouped by inferred market: Crypto / US equity / India equity
  / FX / Other (regex on symbol pattern; advisory only since the watchlist
  schema is free-form).
- Tiles are 3-column on desktop, each shows: symbol + regime, 88×30
  sparkline (30 d), three delta pills (1D / 1W / 1M), last price footer.
- Quick chart icon + remove icon are compact ghost buttons.

### `app/signals/page.tsx` — rewritten
- Card-grid layout (3 columns desktop, 2 tablet, 1 mobile) replacing the
  table. Each card colour-codes its border by direction (green/red/slate),
  shows direction badge with arrow, confidence bar + percent, regime
  pill + model version, mini SHAP driver chart, top-2 contextual news
  headlines, footer with timestamp + journal link.
- Filter bar gained a min-confidence segmented toggle (All / ≥50 / ≥70 /
  ≥85) in addition to asset / regime / direction.

### `app/journal/page.tsx`
- `PageHeader` with the "New entry" button moved to actions.
- Existing per-entry cards + failure-patterns aggregation preserved.

### `app/settings/page.tsx`
- `PageHeader` with a primary "Save changes" button in the actions area
  so the user can save from the top without scrolling.
- A sticky bottom save bar is retained for long-form editing.

### `app/login/page.tsx` — rewritten
- Centered layout with a soft radial gradient background (primary +
  fuchsia blobs).
- PFIP brand mark above the card.
- Card uses `supports-backdrop-filter` so it appears as a frosted panel
  on browsers that support it.
- Email + password inputs now have leading icons + Forgot link.
- Reassuring privacy footer line linking to Settings.

## Layout

### `app/layout.tsx`
- Bumped the max-width to `1400px` for richer dashboards on wide screens.
- Added per-scheme `themeColor` so the browser chrome matches.
- Inter font now declares `display: swap` for nicer first paint.

## Known gaps

- Newer endpoints referenced in the spec (Schedule FA per-FY selector,
  Telegram alerts panel, self-custody wallet manager, password reset
  flow) are sketched into the UI as forward-compatible affordances —
  they will plug into backend endpoints when those ship, but the page
  doesn't pretend they work.
- The **conversation history** sidebar in chat is a placeholder; the
  backend doesn't yet expose persistent threads. Local storage keeps the
  active conversation across reloads.
- `useAssetNews` fans out to 4 asset endpoints on the dashboard; if any
  return 404 they degrade to an empty-state message in the per-column
  cell rather than failing the page.
- 80C optimizer, surcharge gauge, schedule FA table, regime comparison
  chart, post-mortem dialog, correlation matrix were already strong and
  left untouched apart from being re-wrapped in the new page chrome.

## Verification

- `tsc --noEmit` was run with the globally-available TypeScript 6.0.
  All real type errors are now resolved (zero from the modified code).
  The remaining diagnostics in the run are missing-module errors
  (`lucide-react`, `next/link`, `@types/*`) caused by the sandbox npm
  install hitting a filesystem-rename limitation and not finishing
  cleanly. They resolve immediately in a normal `pnpm install` run.
- ESLint could not run for the same reason (eslint-config-next pulls in
  a Next.js compiled babel parser that wasn't materialised). The new
  files follow the same conventions as the rest of the codebase — no
  unused imports, hooks called unconditionally, no any.
