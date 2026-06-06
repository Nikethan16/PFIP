import { describe, it, expect } from "vitest";

import {
  PortfolioSummarySchema,
  SignalSchema,
  OHLCVSchema,
  HoldingSchema,
  WatchlistItemSchema,
  NewsItemSchema,
  RegimeStateSchema,
  PreTradeChecklistSchema,
  PostMortemSchema,
  ProblemSchema,
  MorningBriefSchema,
  TaxSummarySchema,
  JournalEntrySchema,
  CalibrationReportSchema,
  ReliabilityBinSchema,
  ScheduleFARowSchema,
  ScheduleFAResponseSchema,
} from "@/lib/contracts";

// These tests assert the exact runtime-safety the Zod schemas exist for:
// representative REAL backend payloads PARSE, and the old/wrong shapes REJECT.
// The backend is canonical (matches docs/CONTRACTS.md); Decimal columns are
// serialised by Pydantic v2 + FastAPI as JSON *strings*.

describe("PortfolioSummarySchema", () => {
  // Real backend shape: total_inr/pnl_inr are string-encoded Decimals,
  // exposure values are string-encoded Decimals, `drawdown` is a 0..1 fraction.
  const valid = {
    total_inr: "1000000.00",
    pnl_inr: "25000.00",
    pnl_pct: 2.5,
    exposure_by_category: { equity: "600000.00", crypto_exchange: "400000.00" },
    drawdown: 0.042,
  };

  it("accepts the real backend payload and coerces Decimal strings to numbers", () => {
    const parsed = PortfolioSummarySchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.total_inr).toBe(1_000_000);
      expect(parsed.data.exposure_by_category.equity).toBe(600_000);
      expect(parsed.data.drawdown).toBeCloseTo(0.042);
    }
  });

  it("also accepts numeric (non-string) values", () => {
    expect(
      PortfolioSummarySchema.safeParse({ ...valid, total_inr: 1_000_000 })
        .success,
    ).toBe(true);
  });

  it("rejects the OLD shape (realized/unrealized/drawdown_pct/updated_at)", () => {
    expect(
      PortfolioSummarySchema.safeParse({
        total_inr: 1_000_000,
        pnl_inr: 25_000,
        pnl_pct: 2.5,
        realized_pnl_inr: 10_000,
        unrealized_pnl_inr: 15_000,
        drawdown_pct: -4.2,
        exposure_by_category: { equity: 0.6 },
        updated_at: "2026-06-05T03:30:00Z",
        // `drawdown` missing → reject
      }).success,
    ).toBe(false);
  });

  it("rejects an unknown exposure_by_category key", () => {
    expect(
      PortfolioSummarySchema.safeParse({
        ...valid,
        exposure_by_category: { not_a_category: "1" },
      }).success,
    ).toBe(false);
  });
});

describe("SignalSchema", () => {
  const valid = {
    direction: "BUY",
    confidence: 72,
    horizon_hours: 24,
    drivers: [{ feature: "rsi", contribution: 0.4 }],
    counter_arguments: [],
    regime: "bull_trend",
    model_name: "lgbm",
    model_version: "v3",
    asset: "BTC-USD",
    generated_at: "2026-06-05T03:30:00Z",
  };

  it("accepts a valid signal", () => {
    expect(SignalSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects confidence above 100", () => {
    expect(SignalSchema.safeParse({ ...valid, confidence: 101 }).success).toBe(
      false,
    );
  });

  it("rejects a non-integer confidence", () => {
    expect(SignalSchema.safeParse({ ...valid, confidence: 72.5 }).success).toBe(
      false,
    );
  });

  it("rejects an invalid direction enum", () => {
    expect(SignalSchema.safeParse({ ...valid, direction: "LONG" }).success).toBe(
      false,
    );
  });

  it("rejects an unknown regime enum", () => {
    expect(
      SignalSchema.safeParse({ ...valid, regime: "crab_market" }).success,
    ).toBe(false);
  });

  it("rejects more than 5 drivers", () => {
    const drivers = Array.from({ length: 6 }, (_, i) => ({
      feature: `f${i}`,
      contribution: 0.1,
    }));
    expect(SignalSchema.safeParse({ ...valid, drivers }).success).toBe(false);
  });
});

describe("OHLCVSchema", () => {
  // Real backend candle: OHLCV numerics are Decimal → JSON strings.
  const valid = {
    time: "2026-06-05T00:00:00Z",
    symbol: "BTC-USD",
    market: "BTC-USD",
    source: "coinbase",
    timeframe: "1d",
    open: "100.00000000",
    high: "110.00000000",
    low: "95.00000000",
    close: "108.00000000",
    volume: "1234.50000000",
  };

  it("accepts the real backend candle and coerces string numerics to number", () => {
    const parsed = OHLCVSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.close).toBe(108);
      expect(parsed.data.volume).toBeCloseTo(1234.5);
    }
  });

  it("also accepts plain numeric values", () => {
    expect(OHLCVSchema.safeParse({ ...valid, close: 108 }).success).toBe(true);
  });

  it("rejects an unknown source", () => {
    expect(OHLCVSchema.safeParse({ ...valid, source: "mtgox" }).success).toBe(
      false,
    );
  });

  it("rejects an invalid timeframe", () => {
    expect(OHLCVSchema.safeParse({ ...valid, timeframe: "1w" }).success).toBe(
      false,
    );
  });
});

describe("HoldingSchema", () => {
  // Real backend holding: qty/cost_basis_inr are Decimal → strings.
  const valid = {
    id: "11111111-1111-1111-1111-111111111111",
    category: "equity",
    acquired_at: "2026-01-01T00:00:00Z",
    qty: "10",
    cost_basis_inr: "50000.00",
  };

  it("accepts a minimal valid holding, coerces Decimals + applies defaults", () => {
    const parsed = HoldingSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.qty).toBe(10);
      expect(parsed.data.cost_basis_inr).toBe(50_000);
      expect(parsed.data.cost_basis_ccy).toBe("INR");
      expect(parsed.data.is_self_custody).toBe(false);
    }
  });

  it("rejects a non-uuid id", () => {
    expect(HoldingSchema.safeParse({ ...valid, id: "abc" }).success).toBe(false);
  });

  it("rejects an unknown category", () => {
    expect(
      HoldingSchema.safeParse({ ...valid, category: "real_estate" }).success,
    ).toBe(false);
  });
});

describe("WatchlistItemSchema", () => {
  it("accepts the real backend row (market + note, nullable id/added_at)", () => {
    expect(
      WatchlistItemSchema.safeParse({
        id: "11111111-1111-1111-1111-111111111111",
        symbol: "RELIANCE.NS",
        market: "RELIANCE.NS",
        note: "Core position",
        added_at: "2026-06-05T00:00:00Z",
      }).success,
    ).toBe(true);
  });

  it("accepts a row with null id / added_at / note", () => {
    expect(
      WatchlistItemSchema.safeParse({
        id: null,
        symbol: "BTC-USD",
        market: "BTC-USD",
        note: null,
        added_at: null,
      }).success,
    ).toBe(true);
  });

  it("rejects a missing symbol", () => {
    expect(
      WatchlistItemSchema.safeParse({
        market: "X",
        added_at: "2026-06-05T00:00:00Z",
      }).success,
    ).toBe(false);
  });
});

describe("NewsItemSchema", () => {
  const valid = {
    id: "550e8400-e29b-41d4-a716-446655440000",
    time: "2026-06-04T12:00:00Z",
    title: "Markets rally",
    url: "https://example.com/a",
    source: "rss",
    symbol: "BTC-USD",
    sentiment: 0.3,
    summary: null,
  };

  it("accepts a valid item matching the backend NewsItem contract", () => {
    const parsed = NewsItemSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.time).toBe("2026-06-04T12:00:00Z");
      expect(parsed.data.symbol).toBe("BTC-USD");
    }
  });

  it("accepts null id / symbol / sentiment / summary", () => {
    const parsed = NewsItemSchema.safeParse({
      ...valid,
      id: null,
      symbol: null,
      sentiment: null,
      summary: null,
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a non-URL url", () => {
    expect(NewsItemSchema.safeParse({ ...valid, url: "not a url" }).success).toBe(
      false,
    );
  });

  it("rejects the old published_at/tickers shape", () => {
    expect(
      NewsItemSchema.safeParse({
        id: "n1",
        title: "x",
        url: "https://example.com/a",
        source: "rss",
        published_at: "2026-06-05T00:00:00Z",
        tickers: [],
      }).success,
    ).toBe(false);
  });
});

describe("RegimeStateSchema", () => {
  it("rejects confidence outside [0, 1]", () => {
    expect(
      RegimeStateSchema.safeParse({
        regime: "sideways",
        since: "2026-06-05T00:00:00Z",
        confidence: 1.5,
      }).success,
    ).toBe(false);
  });

  it("accepts the unlabelled backend payload (regime 'unknown', since null)", () => {
    expect(
      RegimeStateSchema.safeParse({
        symbol: "BTC-USD",
        regime: "unknown",
        since: null,
        confidence: 0.0,
      }).success,
    ).toBe(true);
  });

  it("still accepts a real labelled regime", () => {
    expect(
      RegimeStateSchema.safeParse({
        regime: "bull_trend",
        since: "2026-06-05T00:00:00Z",
        confidence: 0.82,
      }).success,
    ).toBe(true);
  });
});

describe("PreTradeChecklistSchema", () => {
  const valid = {
    thesis: "BTC breaking out of accumulation range on strong volume.",
    invalidation: "Close below 95k.",
    position_size_pct: 5,
    time_horizon: "2 weeks",
    correlation_check: true,
    liquidity_check: true,
    tax_impact_considered: true,
    news_check: true,
    regime_alignment: true,
    conviction_score: 7,
  };

  it("accepts a complete checklist", () => {
    expect(PreTradeChecklistSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a thesis shorter than 10 chars", () => {
    expect(
      PreTradeChecklistSchema.safeParse({ ...valid, thesis: "too short" })
        .success,
    ).toBe(false);
  });

  it("rejects conviction_score outside 1..10", () => {
    expect(
      PreTradeChecklistSchema.safeParse({ ...valid, conviction_score: 11 })
        .success,
    ).toBe(false);
    expect(
      PreTradeChecklistSchema.safeParse({ ...valid, conviction_score: 0 })
        .success,
    ).toBe(false);
  });

  it("rejects position_size_pct above 100", () => {
    expect(
      PreTradeChecklistSchema.safeParse({ ...valid, position_size_pct: 101 })
        .success,
    ).toBe(false);
  });
});

describe("PostMortemSchema", () => {
  it("accepts a valid post-mortem", () => {
    expect(
      PostMortemSchema.safeParse({
        outcome_pnl_inr: 1000,
        outcome_pnl_pct: 4.2,
        thesis_correct: true,
        followed_plan: true,
        what_worked: "patience",
        what_didnt: "sizing",
        lessons: "size up on high conviction",
      }).success,
    ).toBe(true);
  });

  it("rejects a missing boolean field", () => {
    expect(
      PostMortemSchema.safeParse({
        outcome_pnl_inr: 1000,
        outcome_pnl_pct: 4.2,
        // thesis_correct missing
        followed_plan: true,
        what_worked: "x",
        what_didnt: "y",
        lessons: "z",
      }).success,
    ).toBe(false);
  });
});

describe("JournalEntrySchema", () => {
  // Real backend JournalEntry: flat — symbol (not asset), thesis string,
  // pre_trade_checklist is a {key: bool} map, post_mortem is a markdown string.
  const valid = {
    id: "11111111-1111-1111-1111-111111111111",
    created_at: "2026-06-05T00:00:00Z",
    symbol: "BTC-USD",
    direction: "BUY",
    thesis: "Breakout on volume",
    pre_trade_checklist: { regime_check: true, news_check: false },
    post_mortem: null,
    closed_at: null,
    notes: null,
  };

  it("accepts the real backend journal entry", () => {
    const parsed = JournalEntrySchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.symbol).toBe("BTC-USD");
      expect(parsed.data.pre_trade_checklist.regime_check).toBe(true);
    }
  });

  it("accepts a closed entry with a markdown post_mortem string", () => {
    expect(
      JournalEntrySchema.safeParse({
        ...valid,
        post_mortem: "**Lessons**: size up",
        closed_at: "2026-06-06T00:00:00Z",
      }).success,
    ).toBe(true);
  });

  it("rejects the OLD rich shape (asset + rich pre_trade/post_mortem objects)", () => {
    expect(
      JournalEntrySchema.safeParse({
        id: "11111111-1111-1111-1111-111111111111",
        created_at: "2026-06-05T00:00:00Z",
        asset: "BTC-USD", // wrong key (should be `symbol`)
        direction: "BUY",
        pre_trade: { thesis: "x".repeat(20) },
        post_mortem: { outcome_pnl_inr: 1, lessons: "y" },
      }).success,
    ).toBe(false);
  });
});

describe("CalibrationReportSchema", () => {
  // Real backend /calibration/latest row: created_at (not evaluated_at),
  // reliability bins are {lower, upper, predicted_mean, observed_freq, count}.
  const valid = {
    id: "11111111-1111-1111-1111-111111111111",
    model_name: "lgbm",
    model_version: "v3",
    market: "BTC-USD",
    period_start: "2026-03-01T00:00:00Z",
    period_end: "2026-06-01T00:00:00Z",
    brier: 0.12,
    ece: 0.04,
    sharpness: 0.31,
    n_samples: 500,
    reliability: [
      {
        lower: 0.0,
        upper: 0.1,
        predicted_mean: 0.05,
        observed_freq: 0.06,
        count: 40,
      },
    ],
    created_at: "2026-06-02T00:00:00Z",
  };

  it("accepts the real backend calibration report", () => {
    const parsed = CalibrationReportSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.created_at).toBe("2026-06-02T00:00:00Z");
      expect(parsed.data.reliability[0]?.predicted_mean).toBe(0.05);
    }
  });

  it("rejects the OLD reliability bin shape ({predicted, observed, count})", () => {
    expect(
      ReliabilityBinSchema.safeParse({
        predicted: 0.5,
        observed: 0.5,
        count: 10,
      }).success,
    ).toBe(false);
  });
});

describe("ScheduleFA", () => {
  const row = {
    country: "USA",
    symbol: "AAPL",
    isin: null,
    acquired_on: "2025-04-10",
    peak_balance_usd: "1500.00",
    peak_balance_inr: "124800.00",
    closing_balance_usd: "0",
    closing_balance_inr: "0",
    gross_interest_usd: "0",
    gross_dividend_usd: "12.50",
    gross_proceeds_usd: "0",
  };

  it("accepts a real schedule-FA row and coerces Decimal strings", () => {
    const parsed = ScheduleFARowSchema.safeParse(row);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.peak_balance_inr).toBe(124_800);
      expect(parsed.data.gross_dividend_usd).toBeCloseTo(12.5);
    }
  });

  it("accepts the {disclaimer, fy, schedule, rows} envelope", () => {
    expect(
      ScheduleFAResponseSchema.safeParse({
        disclaimer: "advisory",
        fy: "2026-27",
        schedule: "FA",
        rows: [row],
      }).success,
    ).toBe(true);
  });

  it("rejects the OLD bare-array row shape (asset_type/peak_value_inr/income_inr)", () => {
    expect(
      ScheduleFARowSchema.safeParse({
        country: "USA",
        asset_type: "stock",
        description: "Apple",
        acquired_at: "2025-04-10",
        peak_value_inr: 1,
        closing_value_inr: 0,
        income_inr: 0,
      }).success,
    ).toBe(false);
  });
});

describe("ProblemSchema (RFC 7807)", () => {
  it("defaults type to about:blank when omitted", () => {
    const parsed = ProblemSchema.safeParse({ title: "Bad Request", status: 400 });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.type).toBe("about:blank");
  });

  it("rejects a non-integer status", () => {
    expect(
      ProblemSchema.safeParse({ title: "x", status: 400.5 }).success,
    ).toBe(false);
  });
});

describe("MorningBriefSchema", () => {
  it("defaults headline_items to [] when omitted", () => {
    const parsed = MorningBriefSchema.safeParse({
      date: "2026-06-05",
      markdown: "# Brief",
      generated_at: "2026-06-05T03:30:00Z",
    });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.headline_items).toEqual([]);
  });
});

describe("TaxSummarySchema", () => {
  // Real backend /tax/summary envelope: *_gain_inr/*_tax_inr are string Decimals.
  const valid = {
    disclaimer: "advisory",
    fy: "2026-27",
    equity_stcg_gain_inr: "12000.00",
    equity_ltcg_gain_inr: "30000.00",
    vda_gain_inr: "5000.00",
    vda_tds_credit_inr: "50.00",
    dividend_inr: "1500.00",
    total_tax_inr: "8000.00",
    recommended_regime: "new",
    recommended_itr: "ITR-2",
    surcharge_cliff_warnings: [],
    event_count: 7,
  };

  it("accepts the real backend payload and coerces Decimal strings", () => {
    const parsed = TaxSummarySchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.equity_ltcg_gain_inr).toBe(30_000);
      expect(parsed.data.event_count).toBe(7);
    }
  });

  it("rejects the OLD shape (stcg_equity_inr/updated_at, no event_count)", () => {
    expect(
      TaxSummarySchema.safeParse({
        fy: "2026-27",
        stcg_equity_inr: 1,
        ltcg_equity_inr: 1,
        updated_at: "2026-06-05T00:00:00Z",
      }).success,
    ).toBe(false);
  });
});
