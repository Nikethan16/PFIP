/**
 * Runtime + compile-time contracts mirroring `backend/pfip/core/contracts.py`.
 *
 * ANY change here MUST be reflected in the Pydantic side and vice versa.
 * See /docs/CONTRACTS.md for the canonical spec.
 */

import { z } from "zod";

// -----------------------------------------------------------------------------
// 1. Core enums
// -----------------------------------------------------------------------------

export const MARKETS = [
  "BTC-USD",
  "ETH-USD",
  "SOL-USD",
  "BNB-USD",
  "SPY",
  "QQQ",
  "DIA",
  "VTI",
  "NIFTY50",
  "NIFTY500",
  "NIFTYBEES.NS",
  "SENSEX",
  "USDINR",
  "EURUSD",
  "GBPUSD",
] as const;
// Markets are not exhaustive — any `.NS`/`.BO` ticker may appear. Enum is
// advisory only; the schema itself accepts free-form strings.
export const MarketSchema = z.string().min(1);
export type Market = z.infer<typeof MarketSchema>;

export const SourceSchema = z.enum([
  "coinbase",
  "kraken",
  "bybit",
  "okx",
  "yfinance",
  "stooq",
  "jugaad",
  "amfi",
  "frankfurter",
  "rbi",
  "fred",
  "sec_edgar",
]);
export type Source = z.infer<typeof SourceSchema>;

export const RegimeSchema = z.enum([
  "bull_trend",
  "bear_trend",
  "sideways",
  "high_volatility",
  "accumulation",
  "distribution",
]);
export type Regime = z.infer<typeof RegimeSchema>;

export const HoldingCategorySchema = z.enum([
  "equity",
  "etf",
  "mutual_fund",
  "ppf",
  "epf",
  "nps",
  "fd",
  "sgb",
  "gsec",
  "bond",
  "crypto_exchange",
  "crypto_self_custody",
  "cash",
]);
export type HoldingCategory = z.infer<typeof HoldingCategorySchema>;

export const SignalDirectionSchema = z.enum(["BUY", "HOLD", "SELL"]);
export type SignalDirection = z.infer<typeof SignalDirectionSchema>;

export const TimeframeSchema = z.enum(["1m", "5m", "1h", "1d"]);
export type Timeframe = z.infer<typeof TimeframeSchema>;

// -----------------------------------------------------------------------------
// 2. Signal contract
// -----------------------------------------------------------------------------

export const DriverSchema = z.object({
  feature: z.string(),
  contribution: z.number(),
});
export type Driver = z.infer<typeof DriverSchema>;

export const SignalSchema = z.object({
  direction: SignalDirectionSchema,
  confidence: z.number().int().min(0).max(100),
  horizon_hours: z.number().int().nonnegative(),
  drivers: z.array(DriverSchema).max(5),
  counter_arguments: z.array(DriverSchema).max(3),
  regime: RegimeSchema,
  model_name: z.string(),
  model_version: z.string(),
  asset: z.string(),
  generated_at: z.string(), // ISO-8601 UTC
});
export type Signal = z.infer<typeof SignalSchema>;

// -----------------------------------------------------------------------------
// 3. OHLCV
// -----------------------------------------------------------------------------

// Backend OHLCV (contracts.py) stores open/high/low/close/volume as Decimal,
// which Pydantic v2 + FastAPI serialise as JSON *strings* ("1.5"), per
// CONTRACTS.md §3 (NUMERIC columns). Consumers (charts, sparklines) do numeric
// math on these, so we coerce string→number at the schema boundary.
export const OHLCVSchema = z.object({
  time: z.string(), // ISO-8601 UTC
  symbol: z.string(),
  market: MarketSchema,
  source: SourceSchema,
  timeframe: TimeframeSchema,
  open: z.coerce.number(),
  high: z.coerce.number(),
  low: z.coerce.number(),
  close: z.coerce.number(),
  volume: z.coerce.number(),
});
export type OHLCV = z.infer<typeof OHLCVSchema>;

// -----------------------------------------------------------------------------
// 4. Fundamentals (PIT-aware)
// -----------------------------------------------------------------------------

export const FundamentalsRowSchema = z.object({
  as_of_date: z.string(), // ISO date
  report_date: z.string(),
  symbol: z.string(),
  field: z.string(),
  value: z.number().nullable(),
  source: SourceSchema,
});
export type FundamentalsRow = z.infer<typeof FundamentalsRowSchema>;

// -----------------------------------------------------------------------------
// 5. Portfolio ledger
// -----------------------------------------------------------------------------

// Backend Holding (contracts.py) is strict (extra=forbid). `id` is `UUID | None`
// and the NUMERIC columns (qty, cost_basis_inr, fx_rate, exit_price_inr) are
// Decimal → serialised as JSON *strings*. The holdings table does numeric math
// + formatINR on qty/cost_basis_inr, so coerce string→number here.
// NOTE: the derived *_inr fields below are NOT emitted by /portfolio/holdings
// (strict model rejects them server-side); they remain optional so any future
// enriched endpoint can supply them without a schema change.
export const HoldingSchema = z.object({
  // Backend type is `UUID | None`, but every persisted row from /holdings has a
  // real id; consumers use it as a React key + close target, so we require it.
  id: z.string().uuid(),
  category: HoldingCategorySchema,
  symbol: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  broker: z.string().nullable().optional(),
  account_id: z.string().nullable().optional(),
  acquired_at: z.string(), // ISO-8601 UTC
  qty: z.coerce.number(),
  cost_basis_inr: z.coerce.number(),
  cost_basis_ccy: z.string().default("INR"),
  fx_rate: z.coerce.number().nullable().optional(),
  is_self_custody: z.boolean().default(false),
  notes: z.string().nullable().optional(),
  closed_at: z.string().nullable().optional(),
  exit_price_inr: z.coerce.number().nullable().optional(),
  // Derived fields a future enriched endpoint may return (not from /holdings).
  last_price_inr: z.coerce.number().nullable().optional(),
  market_value_inr: z.coerce.number().nullable().optional(),
  unrealized_pnl_inr: z.coerce.number().nullable().optional(),
  unrealized_pnl_pct: z.coerce.number().nullable().optional(),
});
export type Holding = z.infer<typeof HoldingSchema>;

export const PortfolioTxKindSchema = z.enum([
  "BUY",
  "SELL",
  "DIVIDEND",
  "INTEREST",
  "TRANSFER",
  "FEE",
  "TDS",
]);
export type PortfolioTxKind = z.infer<typeof PortfolioTxKindSchema>;

export const PortfolioTxSchema = z.object({
  id: z.string().uuid(),
  holding_id: z.string().uuid().nullable().optional(),
  time: z.string(),
  kind: PortfolioTxKindSchema,
  qty: z.number().nullable().optional(),
  price: z.number().nullable().optional(),
  amount_inr: z.number(),
  fx_rate: z.number().nullable().optional(),
  tax_withheld: z.number().default(0),
  note: z.string().nullable().optional(),
});
export type PortfolioTx = z.infer<typeof PortfolioTxSchema>;

// Canonical shape per CONTRACTS.md §6 + backend `PortfolioSummary`
// (contracts.py): { total_inr, pnl_inr, pnl_pct, exposure_by_category, drawdown }.
// total_inr/pnl_inr and the exposure values are Decimal → JSON strings (coerced
// to number for the donut chart / formatINR). `drawdown` is a 0..1 *fraction*
// (peak-to-current), NOT a signed percentage. The backend does not emit
// realized/unrealized splits or an updated_at on this endpoint.
export const PortfolioSummarySchema = z.object({
  total_inr: z.coerce.number(),
  pnl_inr: z.coerce.number(),
  pnl_pct: z.number(),
  exposure_by_category: z.record(HoldingCategorySchema, z.coerce.number()),
  drawdown: z.number(),
});
export type PortfolioSummary = z.infer<typeof PortfolioSummarySchema>;

// -----------------------------------------------------------------------------
// 6. Watchlist, news, regime, etc.
// -----------------------------------------------------------------------------

// Canonical backend `WatchlistItem` (contracts.py): { id, symbol, market, note,
// added_at }. `id`/`added_at` are nullable server-side; `market` is required and
// `note` carries the user label. The backend does NOT enrich rows with live
// price / 24h change / regime — those are derived client-side (e.g. from
// /assets/{symbol}/candles) and kept optional so the tile can show them if a
// future endpoint supplies them.
export const WatchlistItemSchema = z.object({
  id: z.string().uuid().nullable().optional(),
  symbol: z.string(),
  market: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
  added_at: z.string().nullable().optional(),
  // Optional client/derived enrichments (not emitted by GET /watchlist).
  last_price: z.coerce.number().nullable().optional(),
  change_pct_24h: z.coerce.number().nullable().optional(),
  regime: RegimeSchema.nullable().optional(),
});
export type WatchlistItem = z.infer<typeof WatchlistItemSchema>;

export const NewsItemSchema = z.object({
  id: z.string().uuid().nullable().optional(),
  time: z.string(), // ISO-8601 UTC
  title: z.string(),
  url: z.string().url(),
  source: z.string(),
  symbol: z.string().nullable().optional(),
  sentiment: z.number().min(-1).max(1).nullable().optional(), // -1..1
  summary: z.string().nullable().optional(),
});
export type NewsItem = z.infer<typeof NewsItemSchema>;

// The backend returns `regime: "unknown"`, `since: null`, `confidence: 0.0`
// when a symbol has not yet been labelled by the classifier. Tolerate that
// neutral, unlabelled state in addition to the six real regime labels.
export const RegimeStateSchema = z.object({
  regime: z.union([RegimeSchema, z.literal("unknown")]),
  since: z.string().nullable().optional(),
  confidence: z.number().min(0).max(1),
});
export type RegimeState = z.infer<typeof RegimeStateSchema>;

// -----------------------------------------------------------------------------
// 7. Calibration
// -----------------------------------------------------------------------------

// Canonical reliability bin as persisted by the calibration runner
// (pfip/calibration/runner.py → JSONB): { lower, upper, predicted_mean,
// observed_freq, count }. NOT { predicted, observed, count }.
export const ReliabilityBinSchema = z.object({
  lower: z.number(),
  upper: z.number(),
  predicted_mean: z.number(),
  observed_freq: z.number(),
  count: z.number().int().nonnegative(),
});
export type ReliabilityBin = z.infer<typeof ReliabilityBinSchema>;

// Canonical backend `GET /calibration/latest` row (pfip/api/calibration.py).
// Note the timestamp is `created_at` (NOT evaluated_at), and the row carries
// market / sharpness / period bounds / id. floats serialise as JSON numbers.
export const CalibrationReportSchema = z.object({
  id: z.string().nullable().optional(),
  model_name: z.string(),
  model_version: z.string(),
  market: z.string().nullable().optional(),
  period_start: z.string().nullable().optional(),
  period_end: z.string().nullable().optional(),
  brier: z.number(),
  ece: z.number(),
  sharpness: z.number().nullable().optional(),
  n_samples: z.number().int(),
  reliability: z.array(ReliabilityBinSchema).default([]),
  created_at: z.string().nullable().optional(),
});
export type CalibrationReport = z.infer<typeof CalibrationReportSchema>;

// -----------------------------------------------------------------------------
// 8. Tax
// -----------------------------------------------------------------------------

// Canonical backend `GET /tax/summary` (pfip/api/tax.py) returns this exact
// envelope. The *_gain_inr / *_tax_inr / *_credit_inr fields are Decimal →
// JSON strings (coerced to number for formatINR). There is NO updated_at,
// interest, foreign-income, or DTAA field on this endpoint — the page renders
// "—"/0 for those. `surcharge_cliff_warnings` is a list of free-text strings.
export const TaxSummarySchema = z.object({
  disclaimer: z.string().optional(),
  fy: z.string(), // "2026-27"
  equity_stcg_gain_inr: z.coerce.number(),
  equity_ltcg_gain_inr: z.coerce.number(),
  vda_gain_inr: z.coerce.number(),
  vda_tds_credit_inr: z.coerce.number(),
  dividend_inr: z.coerce.number(),
  total_tax_inr: z.coerce.number(),
  recommended_regime: z.string().nullable().optional(),
  recommended_itr: z.string().nullable().optional(),
  surcharge_cliff_warnings: z.array(z.string()).default([]),
  event_count: z.number().int(),
});
export type TaxSummary = z.infer<typeof TaxSummarySchema>;

// Canonical backend Schedule FA row (pfip/tax/forms.py::schedule_fa_json).
// All balance/income fields are Decimal → JSON strings (coerced to number for
// formatINR). `acquired_on` may be null. The endpoint wraps these rows in a
// `{ disclaimer, fy, schedule, rows }` envelope — see `useScheduleFA`.
export const ScheduleFARowSchema = z.object({
  country: z.string(),
  symbol: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  acquired_on: z.string().nullable().optional(),
  peak_balance_usd: z.coerce.number(),
  peak_balance_inr: z.coerce.number(),
  closing_balance_usd: z.coerce.number(),
  closing_balance_inr: z.coerce.number(),
  gross_interest_usd: z.coerce.number(),
  gross_dividend_usd: z.coerce.number(),
  gross_proceeds_usd: z.coerce.number(),
});
export type ScheduleFARow = z.infer<typeof ScheduleFARowSchema>;

/** Envelope returned by `GET /tax/schedule-fa` — rows live under `rows`. */
export const ScheduleFAResponseSchema = z.object({
  disclaimer: z.string().optional(),
  fy: z.string(),
  schedule: z.string().optional(),
  rows: z.array(ScheduleFARowSchema).default([]),
});
export type ScheduleFAResponse = z.infer<typeof ScheduleFAResponseSchema>;

// -----------------------------------------------------------------------------
// 9. Agent / chat
// -----------------------------------------------------------------------------

export const MorningBriefSchema = z.object({
  date: z.string(),
  markdown: z.string(),
  headline_items: z
    .array(
      z.object({
        symbol: z.string(),
        note: z.string(),
      }),
    )
    .default([]),
  generated_at: z.string(),
});
export type MorningBrief = z.infer<typeof MorningBriefSchema>;

export const ChatMessageSchema = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant", "system"]),
  content: z.string(),
  created_at: z.string(),
  sources: z
    .array(
      z.object({
        type: z.enum(["kb", "news", "db"]),
        id: z.string(),
        title: z.string(),
      }),
    )
    .default([]),
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

// -----------------------------------------------------------------------------
// 10. Journal (pre-trade checklist + post-mortem)
// -----------------------------------------------------------------------------

export const PreTradeChecklistSchema = z.object({
  thesis: z.string().min(10, "State your thesis (≥ 10 chars)."),
  invalidation: z.string().min(5, "What makes this wrong?"),
  position_size_pct: z.number().min(0).max(100),
  stop_loss_pct: z.number().min(0).max(100).nullable().optional(),
  time_horizon: z.string(),
  correlation_check: z.boolean(),
  liquidity_check: z.boolean(),
  tax_impact_considered: z.boolean(),
  news_check: z.boolean(),
  regime_alignment: z.boolean(),
  conviction_score: z.number().int().min(1).max(10),
});
export type PreTradeChecklist = z.infer<typeof PreTradeChecklistSchema>;

export const PostMortemSchema = z.object({
  outcome_pnl_inr: z.number(),
  outcome_pnl_pct: z.number(),
  thesis_correct: z.boolean(),
  followed_plan: z.boolean(),
  what_worked: z.string(),
  what_didnt: z.string(),
  lessons: z.string(),
  next_actions: z.string().nullable().optional(),
});
export type PostMortem = z.infer<typeof PostMortemSchema>;

// Canonical backend `JournalEntry` (contracts.py, strict). NOTE the shape is
// flatter than the UI's aspirational rich objects:
//   - `symbol` (NOT `asset`)
//   - `thesis` is a top-level free-text string
//   - `pre_trade_checklist` is a plain dict of booleans (Appendix B keys), not
//     the rich PreTradeChecklist object
//   - `post_mortem` is a free-text markdown string (NOT a PostMortem object)
//   - `notes` is an optional free-text field
// `id` is `UUID | None` server-side but persisted rows always carry one.
export const JournalEntrySchema = z.object({
  id: z.string().uuid(),
  created_at: z.string(),
  symbol: z.string(),
  direction: SignalDirectionSchema,
  thesis: z.string(),
  pre_trade_checklist: z.record(z.string(), z.boolean()).default({}),
  post_mortem: z.string().nullable().optional(),
  closed_at: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
});
export type JournalEntry = z.infer<typeof JournalEntrySchema>;

// -----------------------------------------------------------------------------
// 11. Error (RFC 7807)
// -----------------------------------------------------------------------------

export const ProblemSchema = z.object({
  type: z.string().default("about:blank"),
  title: z.string(),
  status: z.number().int(),
  detail: z.string().optional(),
  instance: z.string().optional(),
});
export type Problem = z.infer<typeof ProblemSchema>;
