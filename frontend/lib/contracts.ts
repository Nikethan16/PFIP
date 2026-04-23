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

export const OHLCVSchema = z.object({
  time: z.string(), // ISO-8601 UTC
  symbol: z.string(),
  market: MarketSchema,
  source: SourceSchema,
  timeframe: TimeframeSchema,
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number(),
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

export const HoldingSchema = z.object({
  id: z.string().uuid(),
  category: HoldingCategorySchema,
  symbol: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  broker: z.string().nullable().optional(),
  account_id: z.string().nullable().optional(),
  acquired_at: z.string(), // ISO-8601 UTC
  qty: z.number(),
  cost_basis_inr: z.number(),
  cost_basis_ccy: z.string().default("INR"),
  fx_rate: z.number().nullable().optional(),
  is_self_custody: z.boolean().default(false),
  notes: z.string().nullable().optional(),
  closed_at: z.string().nullable().optional(),
  exit_price_inr: z.number().nullable().optional(),
  // Derived fields the backend may return in /summary endpoints.
  last_price_inr: z.number().nullable().optional(),
  market_value_inr: z.number().nullable().optional(),
  unrealized_pnl_inr: z.number().nullable().optional(),
  unrealized_pnl_pct: z.number().nullable().optional(),
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

export const PortfolioSummarySchema = z.object({
  total_inr: z.number(),
  pnl_inr: z.number(),
  pnl_pct: z.number(),
  realized_pnl_inr: z.number(),
  unrealized_pnl_inr: z.number(),
  drawdown_pct: z.number(),
  exposure_by_category: z.record(HoldingCategorySchema, z.number()),
  updated_at: z.string(),
});
export type PortfolioSummary = z.infer<typeof PortfolioSummarySchema>;

// -----------------------------------------------------------------------------
// 6. Watchlist, news, regime, etc.
// -----------------------------------------------------------------------------

export const WatchlistItemSchema = z.object({
  id: z.string().uuid(),
  symbol: z.string(),
  label: z.string().nullable().optional(),
  added_at: z.string(),
  last_price: z.number().nullable().optional(),
  change_pct_24h: z.number().nullable().optional(),
  regime: RegimeSchema.nullable().optional(),
});
export type WatchlistItem = z.infer<typeof WatchlistItemSchema>;

export const NewsItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string().nullable().optional(),
  url: z.string().url(),
  source: z.string(),
  published_at: z.string(),
  tickers: z.array(z.string()).default([]),
  sentiment: z.number().nullable().optional(), // -1..1
});
export type NewsItem = z.infer<typeof NewsItemSchema>;

export const RegimeStateSchema = z.object({
  regime: RegimeSchema,
  since: z.string(),
  confidence: z.number().min(0).max(1),
});
export type RegimeState = z.infer<typeof RegimeStateSchema>;

// -----------------------------------------------------------------------------
// 7. Calibration
// -----------------------------------------------------------------------------

export const ReliabilityBinSchema = z.object({
  predicted: z.number(),
  observed: z.number(),
  count: z.number().int().nonnegative(),
});
export type ReliabilityBin = z.infer<typeof ReliabilityBinSchema>;

export const CalibrationReportSchema = z.object({
  model_name: z.string(),
  model_version: z.string(),
  brier: z.number(),
  ece: z.number(),
  n_samples: z.number().int(),
  reliability: z.array(ReliabilityBinSchema),
  evaluated_at: z.string(),
});
export type CalibrationReport = z.infer<typeof CalibrationReportSchema>;

// -----------------------------------------------------------------------------
// 8. Tax
// -----------------------------------------------------------------------------

export const TaxSummarySchema = z.object({
  fy: z.string(), // "2026-27"
  stcg_equity_inr: z.number(),
  ltcg_equity_inr: z.number(),
  stcg_crypto_inr: z.number(),
  ltcg_crypto_inr: z.number(),
  crypto_flat_tax_inr: z.number(),
  dividend_income_inr: z.number(),
  interest_income_inr: z.number(),
  foreign_income_inr: z.number(),
  dtaa_credit_available_inr: z.number(),
  total_tax_liability_inr: z.number(),
  updated_at: z.string(),
});
export type TaxSummary = z.infer<typeof TaxSummarySchema>;

export const ScheduleFARowSchema = z.object({
  country: z.string(),
  asset_type: z.string(),
  description: z.string(),
  acquired_at: z.string(),
  peak_value_inr: z.number(),
  closing_value_inr: z.number(),
  income_inr: z.number(),
});
export type ScheduleFARow = z.infer<typeof ScheduleFARowSchema>;

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

export const JournalEntrySchema = z.object({
  id: z.string().uuid(),
  created_at: z.string(),
  asset: z.string(),
  direction: SignalDirectionSchema,
  pre_trade: PreTradeChecklistSchema,
  post_mortem: PostMortemSchema.nullable().optional(),
  closed_at: z.string().nullable().optional(),
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
