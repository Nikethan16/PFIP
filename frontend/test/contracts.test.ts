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
} from "@/lib/contracts";

// These tests assert the exact runtime-safety the Zod schemas exist for:
// representative valid backend payloads PARSE, malformed ones are REJECTED.

describe("PortfolioSummarySchema", () => {
  const valid = {
    total_inr: 1_000_000,
    pnl_inr: 25_000,
    pnl_pct: 2.5,
    realized_pnl_inr: 10_000,
    unrealized_pnl_inr: 15_000,
    drawdown_pct: -4.2,
    exposure_by_category: { equity: 0.6, crypto_exchange: 0.4 },
    updated_at: "2026-06-05T03:30:00Z",
  };

  it("accepts a representative payload", () => {
    expect(PortfolioSummarySchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a missing required numeric field", () => {
    const { total_inr, ...rest } = valid;
    void total_inr;
    expect(PortfolioSummarySchema.safeParse(rest).success).toBe(false);
  });

  it("rejects a stringified number for total_inr (no coercion)", () => {
    expect(
      PortfolioSummarySchema.safeParse({ ...valid, total_inr: "1000000" })
        .success,
    ).toBe(false);
  });

  it("rejects an unknown exposure_by_category key", () => {
    expect(
      PortfolioSummarySchema.safeParse({
        ...valid,
        exposure_by_category: { not_a_category: 1 },
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
  const valid = {
    time: "2026-06-05T00:00:00Z",
    symbol: "BTC-USD",
    market: "BTC-USD",
    source: "coinbase",
    timeframe: "1d",
    open: 100,
    high: 110,
    low: 95,
    close: 108,
    volume: 1234.5,
  };

  it("accepts a valid candle", () => {
    expect(OHLCVSchema.safeParse(valid).success).toBe(true);
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
  const valid = {
    id: "11111111-1111-1111-1111-111111111111",
    category: "equity",
    acquired_at: "2026-01-01T00:00:00Z",
    qty: 10,
    cost_basis_inr: 50_000,
  };

  it("accepts a minimal valid holding and applies defaults", () => {
    const parsed = HoldingSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      // cost_basis_ccy defaults to INR, is_self_custody defaults to false.
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
  it("accepts a row with optional fields omitted", () => {
    expect(
      WatchlistItemSchema.safeParse({
        id: "11111111-1111-1111-1111-111111111111",
        symbol: "RELIANCE.NS",
        added_at: "2026-06-05T00:00:00Z",
      }).success,
    ).toBe(true);
  });

  it("rejects a missing symbol", () => {
    expect(
      WatchlistItemSchema.safeParse({
        id: "11111111-1111-1111-1111-111111111111",
        added_at: "2026-06-05T00:00:00Z",
      }).success,
    ).toBe(false);
  });
});

describe("NewsItemSchema", () => {
  const valid = {
    id: "n1",
    title: "Markets rally",
    url: "https://example.com/a",
    source: "reuters",
    published_at: "2026-06-05T00:00:00Z",
  };

  it("accepts a valid item and defaults tickers to []", () => {
    const parsed = NewsItemSchema.safeParse(valid);
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.tickers).toEqual([]);
  });

  it("rejects a non-URL url", () => {
    expect(NewsItemSchema.safeParse({ ...valid, url: "not a url" }).success).toBe(
      false,
    );
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
  it("rejects when a required numeric field is missing", () => {
    expect(
      TaxSummarySchema.safeParse({
        fy: "2026-27",
        // most numeric fields missing
        updated_at: "2026-06-05T00:00:00Z",
      }).success,
    ).toBe(false);
  });
});
