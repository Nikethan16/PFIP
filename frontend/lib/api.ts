"use client";

/**
 * Centralised API client. Every network call to the backend funnels through
 * `apiFetch`, and every page/component consumes it via a TanStack Query hook
 * defined here. This keeps Zod validation + auth headers in exactly one place.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { z, type ZodTypeAny } from "zod";
import { signOut } from "next-auth/react";
import { useSession } from "next-auth/react";

import {
  CalibrationReportSchema,
  HoldingSchema,
  JournalEntrySchema,
  MorningBriefSchema,
  NewsItemSchema,
  OHLCVSchema,
  PortfolioSummarySchema,
  PostMortemSchema,
  PreTradeChecklistSchema,
  ProblemSchema,
  RegimeStateSchema,
  ScheduleFAResponseSchema,
  SignalSchema,
  TaxSummarySchema,
  WatchlistItemSchema,
  type CalibrationReport,
  type Holding,
  type JournalEntry,
  type MorningBrief,
  type NewsItem,
  type OHLCV,
  type PortfolioSummary,
  type PostMortem,
  type PreTradeChecklist,
  type RegimeState,
  type ScheduleFARow,
  type ScheduleFAResponse,
  type Signal,
  type TaxSummary,
  type WatchlistItem,
} from "./contracts";

// -----------------------------------------------------------------------------
// Core fetch wrapper
// -----------------------------------------------------------------------------

// Normalise the configured API base so it ALWAYS ends with /api/v1, regardless
// of whether the env var was set with or without the suffix. Prevents the
// "every page 404s" footgun if NEXT_PUBLIC_API_URL is set to bare host.
const RAW_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const API_BASE = RAW_API_BASE.replace(/\/+$/, "").endsWith("/api/v1")
  ? RAW_API_BASE.replace(/\/+$/, "")
  : `${RAW_API_BASE.replace(/\/+$/, "")}/api/v1`;

/**
 * Current Indian fiscal year as "YYYY-YY" (Apr 1 – Mar 31). The backend's
 * `/tax/*` endpoints take `fy` as a REQUIRED query param, so callers that don't
 * supply one fall back to this rather than 422-ing.
 */
export function currentFy(now: Date = new Date()): string {
  const y = now.getFullYear();
  // Months are 0-based; Jan–Mar (0–2) belong to the FY that started the prior year.
  const startYear = now.getMonth() >= 3 ? y : y - 1;
  const endYY = String((startYear + 1) % 100).padStart(2, "0");
  return `${startYear}-${endYY}`;
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly problem: z.infer<typeof ProblemSchema> | null;

  constructor(
    message: string,
    status: number,
    problem: z.infer<typeof ProblemSchema> | null,
  ) {
    super(message);
    this.status = status;
    this.problem = problem;
  }
}

interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  token?: string | null;
}

export async function apiFetch<T>(
  path: string,
  schema: ZodTypeAny,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { body, token, headers, ...rest } = options;

  const resolvedHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  if (body !== undefined && !(body instanceof FormData)) {
    resolvedHeaders["Content-Type"] = "application/json";
  }

  if (token) {
    resolvedHeaders["Authorization"] = `Bearer ${token}`;
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: resolvedHeaders,
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });

  if (resp.status === 401) {
    // Token expired or invalid — drop the session AND bounce the user to the
    // login page so an expired session never leaves them on a broken shell.
    await signOut({ callbackUrl: "/login" });
    throw new ApiError("Unauthorized", 401, null);
  }

  let json: unknown = null;
  try {
    json = await resp.json();
  } catch {
    // Non-JSON response (e.g. 204).
  }

  if (!resp.ok) {
    const parsed = ProblemSchema.safeParse(json);
    throw new ApiError(
      parsed.success ? parsed.data.title : `HTTP ${resp.status}`,
      resp.status,
      parsed.success ? parsed.data : null,
    );
  }

  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    // eslint-disable-next-line no-console
    console.error("[apiFetch] schema validation failed", parsed.error.issues);
    throw new ApiError(
      "Response failed schema validation",
      resp.status,
      null,
    );
  }
  return parsed.data as T;
}

// -----------------------------------------------------------------------------
// Auth helper
// -----------------------------------------------------------------------------

/** Extract the backend JWT from the current NextAuth session (if any). */
export function useAuthToken(): string | null {
  const { data } = useSession();
  const token = (data as unknown as { backendToken?: string } | null)
    ?.backendToken;
  return token ?? null;
}

// -----------------------------------------------------------------------------
// Query hooks
// -----------------------------------------------------------------------------

interface UseCandlesArgs {
  symbol: string;
  timeframe?: "1m" | "5m" | "1h" | "1d";
  since?: string;
  until?: string;
}

export function useCandles({
  symbol,
  timeframe = "1d",
  since,
  until,
}: UseCandlesArgs): UseQueryResult<OHLCV[]> {
  const token = useAuthToken();
  const qs = new URLSearchParams({ timeframe });
  if (since) qs.set("since", since);
  if (until) qs.set("until", until);

  return useQuery<OHLCV[]>({
    queryKey: ["candles", symbol, timeframe, since, until],
    queryFn: () =>
      apiFetch<OHLCV[]>(
        `/assets/${encodeURIComponent(symbol)}/candles?${qs.toString()}`,
        z.array(OHLCVSchema),
        { token },
      ),
    staleTime: 60_000,
  });
}

export function useAssetRegime(symbol: string): UseQueryResult<RegimeState> {
  const token = useAuthToken();
  return useQuery<RegimeState>({
    queryKey: ["regime", symbol],
    queryFn: () =>
      apiFetch<RegimeState>(
        `/assets/${encodeURIComponent(symbol)}/regime`,
        RegimeStateSchema,
        { token },
      ),
    staleTime: 5 * 60_000,
  });
}

export function useAssetNews(symbol: string): UseQueryResult<NewsItem[]> {
  const token = useAuthToken();
  return useQuery<NewsItem[]>({
    queryKey: ["news", symbol],
    queryFn: () =>
      apiFetch<NewsItem[]>(
        `/assets/${encodeURIComponent(symbol)}/news?limit=20`,
        z.array(NewsItemSchema),
        { token },
      ),
    staleTime: 2 * 60_000,
  });
}

/**
 * Latest computed feature row for an asset. Backend: `GET /assets/{symbol}/features`.
 * The canonical typed indicators live under `features`; anything else the
 * compute flow emitted is in the `extras` JSONB blob. When the Prefect compute
 * flow hasn't run for this symbol yet the backend returns a well-formed payload
 * with `as_of: null` and every feature null (rather than 404) — the schema below
 * mirrors that so the hook never throws on a fresh install.
 */
export interface AssetFeatures {
  symbol: string;
  timeframe: string;
  as_of: string | null;
  source: string | null;
  features: {
    rsi_14: number | null;
    macd: number | null;
    macd_signal: number | null;
    macd_hist: number | null;
    atr_14: number | null;
    return_7d: number | null;
    volatility_30d: number | null;
  };
  extras: Record<string, unknown>;
}

const AssetFeaturesSchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  as_of: z.string().nullable(),
  source: z.string().nullable(),
  features: z.object({
    rsi_14: z.number().nullable(),
    macd: z.number().nullable(),
    macd_signal: z.number().nullable(),
    macd_hist: z.number().nullable(),
    atr_14: z.number().nullable(),
    return_7d: z.number().nullable(),
    volatility_30d: z.number().nullable(),
  }),
  extras: z.record(z.string(), z.unknown()).default({}),
});

export function useAssetFeatures(
  symbol: string,
  opts: { timeframe?: string } = {},
): UseQueryResult<AssetFeatures> {
  const token = useAuthToken();
  const timeframe = opts.timeframe ?? "1d";
  return useQuery<AssetFeatures>({
    queryKey: ["features", symbol, timeframe],
    queryFn: () =>
      apiFetch<AssetFeatures>(
        `/assets/${encodeURIComponent(symbol)}/features?timeframe=${encodeURIComponent(timeframe)}`,
        AssetFeaturesSchema,
        { token },
      ),
    staleTime: 5 * 60_000,
  });
}

export function useWatchlist(): UseQueryResult<WatchlistItem[]> {
  const token = useAuthToken();
  return useQuery<WatchlistItem[]>({
    queryKey: ["watchlist"],
    queryFn: () =>
      apiFetch<WatchlistItem[]>(
        `/watchlist`,
        z.array(WatchlistItemSchema),
        { token },
      ),
    staleTime: 30_000,
  });
}

export function useAddWatchlist(): UseMutationResult<
  WatchlistItem,
  unknown,
  { symbol: string; market?: string; note?: string }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars) =>
      // Backend `WatchlistCreate` is strict and requires { symbol, market, note? }.
      // `market` defaults to the symbol when the caller doesn't classify it.
      apiFetch<WatchlistItem>(`/watchlist`, WatchlistItemSchema, {
        method: "POST",
        body: {
          symbol: vars.symbol,
          market: vars.market ?? vars.symbol,
          ...(vars.note != null ? { note: vars.note } : {}),
        },
        token,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

export function useRemoveWatchlist(): UseMutationResult<
  null,
  unknown,
  { id: string }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }) =>
      apiFetch<null>(`/watchlist/${id}`, z.null().nullable().transform(() => null), {
        method: "DELETE",
        token,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

export function useSignals(asset?: string): UseQueryResult<Signal[]> {
  const token = useAuthToken();
  return useQuery<Signal[]>({
    queryKey: ["signals", asset ?? "all"],
    queryFn: () => {
      const qs = asset ? `?asset=${encodeURIComponent(asset)}` : "";
      return apiFetch<Signal[]>(
        `/signals${qs}`,
        z.array(SignalSchema),
        { token },
      );
    },
    staleTime: 30_000,
  });
}

export function useLatestSignals(): UseQueryResult<Signal[]> {
  const token = useAuthToken();
  return useQuery<Signal[]>({
    queryKey: ["signals", "latest"],
    queryFn: () =>
      apiFetch<Signal[]>(`/signals/latest`, z.array(SignalSchema), { token }),
    staleTime: 30_000,
  });
}

export function useHoldings(): UseQueryResult<Holding[]> {
  const token = useAuthToken();
  return useQuery<Holding[]>({
    queryKey: ["holdings"],
    queryFn: () =>
      apiFetch<Holding[]>(
        `/portfolio/holdings`,
        z.array(HoldingSchema),
        { token },
      ),
    staleTime: 60_000,
  });
}

/** Response from `POST /portfolio/holdings/{id}/close`. */
export interface ClosePositionResult {
  holding: Holding;
  sell_tx: {
    holding_id: string;
    time: string;
    qty: string;
    price_inr: string;
    amount_inr: string;
  };
  post_mortem_required: boolean;
  /** Journal entry id of the auto-created post-mortem stub (audit H4). */
  journal_entry_id: string;
  disclaimer: string;
}

const ClosePositionResultSchema = z.object({
  holding: HoldingSchema,
  sell_tx: z.object({
    holding_id: z.string(),
    time: z.string(),
    qty: z.string(),
    price_inr: z.string(),
    amount_inr: z.string(),
  }),
  post_mortem_required: z.boolean(),
  journal_entry_id: z.string().uuid(),
  disclaimer: z.string(),
});

export function useClosePosition(): UseMutationResult<
  ClosePositionResult,
  unknown,
  { holdingId: string; exit_price_inr: number; qty?: number; when?: string }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ holdingId, exit_price_inr, qty, when }) =>
      apiFetch<ClosePositionResult>(
        `/portfolio/holdings/${holdingId}/close`,
        ClosePositionResultSchema,
        {
          method: "POST",
          body: {
            exit_price_inr,
            ...(qty != null ? { qty } : {}),
            ...(when != null ? { when } : {}),
          },
          token,
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holdings"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["journal"] });
    },
  });
}

export function usePortfolioSummary(): UseQueryResult<PortfolioSummary> {
  const token = useAuthToken();
  return useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary"],
    queryFn: () =>
      apiFetch<PortfolioSummary>(
        `/portfolio/summary`,
        PortfolioSummarySchema,
        { token },
      ),
    staleTime: 60_000,
  });
}

/**
 * Mark-to-market coverage. Backend: `GET /portfolio/marking`.
 * Tells the UI which holdings are live-priced vs cost-basis, and why any
 * fell back (no_price / unknown_currency / no_fx_rate).
 */
export interface MarkingUnmarked {
  symbol: string;
  reason: string;
}

export interface Marking {
  as_of: string | null;
  usdinr: string | null;
  marked: string[];
  unmarked: MarkingUnmarked[];
  mark_prices_inr: Record<string, string>;
  coverage: { marked: number; total: number };
  disclaimer: string;
}

const MarkingSchema = z.object({
  as_of: z.string().nullable(),
  usdinr: z.string().nullable(),
  marked: z.array(z.string()),
  unmarked: z.array(
    z.object({
      symbol: z.string(),
      reason: z.string(),
    }),
  ),
  mark_prices_inr: z.record(z.string(), z.string()),
  coverage: z.object({
    marked: z.number().int(),
    total: z.number().int(),
  }),
  disclaimer: z.string(),
});

export function useMarking(): UseQueryResult<Marking> {
  const token = useAuthToken();
  return useQuery<Marking>({
    queryKey: ["portfolio", "marking"],
    queryFn: () =>
      apiFetch<Marking>(`/portfolio/marking`, MarkingSchema, { token }),
    staleTime: 60_000,
  });
}

export function useMorningBrief(date?: string): UseQueryResult<MorningBrief> {
  const token = useAuthToken();
  return useQuery<MorningBrief>({
    queryKey: ["morning-brief", date ?? "today"],
    queryFn: async () => {
      // Backend `GET /agent/morning-brief` returns a PlainTextResponse (rendered
      // Markdown), NOT JSON — see CONTRACTS.md §6. apiFetch assumes JSON, so we
      // fetch the text directly and adapt it to the MorningBrief shape the card
      // renders. `headline_items` isn't produced by this endpoint.
      const qs = date ? `?date=${date}` : "";
      const resp = await fetch(`${API_BASE}/agent/morning-brief${qs}`, {
        headers: {
          Accept: "text/plain, text/markdown, */*",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (resp.status === 401) {
        await signOut({ callbackUrl: "/login" });
        throw new ApiError("Unauthorized", 401, null);
      }
      if (!resp.ok) {
        throw new ApiError(`HTTP ${resp.status}`, resp.status, null);
      }
      const markdown = await resp.text();
      return MorningBriefSchema.parse({
        date: (date ?? new Date().toISOString().slice(0, 10)),
        markdown,
        headline_items: [],
        generated_at: new Date().toISOString(),
      });
    },
    staleTime: 10 * 60_000,
  });
}

export function useCalibration(): UseQueryResult<CalibrationReport[]> {
  const token = useAuthToken();
  return useQuery<CalibrationReport[]>({
    queryKey: ["calibration", "latest"],
    queryFn: () =>
      apiFetch<CalibrationReport[]>(
        `/calibration/latest`,
        z.array(CalibrationReportSchema),
        { token },
      ),
    staleTime: 15 * 60_000,
  });
}

export function useTaxSummary(fy?: string): UseQueryResult<TaxSummary> {
  const token = useAuthToken();
  return useQuery<TaxSummary>({
    queryKey: ["tax", "summary", fy ?? "current"],
    queryFn: () => {
      // `fy` is REQUIRED server-side; default to the current Indian FY.
      const resolvedFy = fy ?? currentFy();
      return apiFetch<TaxSummary>(
        `/tax/summary?fy=${encodeURIComponent(resolvedFy)}`,
        TaxSummarySchema,
        { token },
      );
    },
    staleTime: 10 * 60_000,
  });
}

/** Tax-loss harvesting plan response from `POST /api/v1/tax/harvest`. */
export interface HarvestSuggestion {
  lot_id: string;
  symbol: string;
  asset_class: string;
  term: "STCG" | "LTCG";
  qty: string;
  loss_inr: string;
  offsets_against: string;
  estimated_tax_saved_inr: string;
  warning: string | null;
}

export interface HarvestPlan {
  disclaimer: string;
  fy: string;
  total_loss_inr: string;
  total_tax_saved_inr: string;
  suggestions: HarvestSuggestion[];
  n_lots_evaluated: number;
}

export interface HarvestRequest {
  fy: string;
  realised_stcg_equity_inr?: number;
  realised_ltcg_equity_inr?: number;
  realised_debt_gain_inr?: number;
  marginal_slab_rate?: number;
  surcharge_rate?: number;
}

const HarvestSuggestionSchema = z.object({
  lot_id: z.string(),
  symbol: z.string(),
  asset_class: z.string(),
  term: z.enum(["STCG", "LTCG"]),
  qty: z.string(),
  loss_inr: z.string(),
  offsets_against: z.string(),
  estimated_tax_saved_inr: z.string(),
  warning: z.string().nullable(),
});

const HarvestPlanSchema = z.object({
  disclaimer: z.string(),
  fy: z.string(),
  total_loss_inr: z.string(),
  total_tax_saved_inr: z.string(),
  suggestions: z.array(HarvestSuggestionSchema),
  n_lots_evaluated: z.number(),
});

/** One Prefect deployment row from `GET /api/v1/schedules`. */
export interface ScheduleRow {
  name: string;
  tags: string[];
  cron: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  age_hours: number | null;
}

export interface SchedulesPayload {
  deployments: ScheduleRow[];
  error: string | null;
}

const ScheduleRowSchema = z.object({
  name: z.string(),
  tags: z.array(z.string()),
  cron: z.string().nullable(),
  last_run_at: z.string().nullable(),
  last_success_at: z.string().nullable(),
  age_hours: z.number().nullable(),
});

const SchedulesPayloadSchema = z.object({
  deployments: z.array(ScheduleRowSchema),
  error: z.string().nullable(),
});

export function useSchedules(): UseQueryResult<SchedulesPayload> {
  const token = useAuthToken();
  return useQuery<SchedulesPayload>({
    queryKey: ["ops", "schedules"],
    queryFn: () =>
      apiFetch<SchedulesPayload>(`/schedules`, SchedulesPayloadSchema, {
        token,
      }),
    refetchInterval: 60_000,
  });
}

/** Model registry entry from `GET /api/v1/models`. */
export interface ModelEntry {
  id: string;
  name: string;
  kind: string;
  task: string;
  regime: string | null;
  horizon: string | null;
  version: string;
  created_at: string;
  artefact_relpath: string;
  schema_revision: string | null;
  sha256: string;
  metrics: Record<string, number>;
  notes: string;
  pinned_for: string[];
}

const ModelEntrySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  task: z.string(),
  regime: z.string().nullable(),
  horizon: z.string().nullable(),
  version: z.string(),
  created_at: z.string(),
  artefact_relpath: z.string(),
  schema_revision: z.string().nullable(),
  sha256: z.string(),
  metrics: z.record(z.string(), z.number()),
  notes: z.string(),
  pinned_for: z.array(z.string()),
});

export function useModels(opts: {
  task?: string;
  regime?: string;
  horizon?: string;
} = {}): UseQueryResult<ModelEntry[]> {
  const token = useAuthToken();
  return useQuery<ModelEntry[]>({
    queryKey: ["models", opts],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.task) qs.set("task", opts.task);
      if (opts.regime) qs.set("regime", opts.regime);
      if (opts.horizon) qs.set("horizon", opts.horizon);
      const q = qs.toString();
      return apiFetch<ModelEntry[]>(
        `/models${q ? `?${q}` : ""}`,
        z.array(ModelEntrySchema),
        { token },
      );
    },
    staleTime: 5 * 60_000,
  });
}

export function usePinModel(): UseMutationResult<ModelEntry, unknown, { modelId: string; slot: string }> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ modelId, slot }) =>
      apiFetch<ModelEntry>(
        `/models/${modelId}/pin`,
        ModelEntrySchema,
        {
          method: "POST",
          body: { slot },
          token,
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useHarvestPlan(): UseMutationResult<HarvestPlan, unknown, HarvestRequest> {
  const token = useAuthToken();
  return useMutation({
    mutationFn: (vars: HarvestRequest) =>
      apiFetch<HarvestPlan>(`/tax/harvest`, HarvestPlanSchema, {
        method: "POST",
        body: {
          realised_stcg_equity_inr: 0,
          realised_ltcg_equity_inr: 0,
          realised_debt_gain_inr: 0,
          marginal_slab_rate: 0.3,
          surcharge_rate: 0,
          ...vars,
        },
        token,
      }),
  });
}

export function useScheduleFA(fy?: string): UseQueryResult<ScheduleFARow[]> {
  const token = useAuthToken();
  return useQuery<ScheduleFARow[]>({
    queryKey: ["tax", "schedule-fa", fy ?? "current"],
    queryFn: async () => {
      // `fy` is REQUIRED server-side; default to the current Indian FY.
      const resolvedFy = fy ?? currentFy();
      // Backend returns a `{ disclaimer, fy, schedule, rows }` envelope, not a
      // bare array. Validate the envelope, then hand the page just the rows.
      const env = await apiFetch<ScheduleFAResponse>(
        `/tax/schedule-fa?fy=${encodeURIComponent(resolvedFy)}`,
        ScheduleFAResponseSchema,
        { token },
      );
      return env.rows;
    },
    staleTime: 30 * 60_000,
  });
}

export function useJournalEntries(): UseQueryResult<JournalEntry[]> {
  const token = useAuthToken();
  return useQuery<JournalEntry[]>({
    queryKey: ["journal", "entries"],
    queryFn: () =>
      apiFetch<JournalEntry[]>(
        `/journal/entries`,
        z.array(JournalEntrySchema),
        { token },
      ),
    staleTime: 60_000,
  });
}

/** Failure-pattern row returned by `GET /journal/patterns`. */
export interface JournalFailurePattern {
  pattern: string;
  count: number;
  examples: string[];
}

const JournalFailurePatternSchema = z.object({
  pattern: z.string(),
  count: z.number(),
  examples: z.array(z.string()),
});

export function useJournalPatterns(
  opts: { days?: number; top?: number } = {},
): UseQueryResult<JournalFailurePattern[]> {
  const token = useAuthToken();
  const days = opts.days ?? 30;
  const top = opts.top ?? 5;
  return useQuery<JournalFailurePattern[]>({
    queryKey: ["journal", "patterns", { days, top }],
    queryFn: () =>
      apiFetch<JournalFailurePattern[]>(
        `/journal/patterns?days=${days}&top=${top}`,
        z.array(JournalFailurePatternSchema),
        { token },
      ),
    staleTime: 60_000 * 5,
  });
}

// The 10 Appendix-B keys the backend's JournalEntryCreate requires (all must be
// present and True). Keep in lockstep with backend journal.py::_REQUIRED_CHECKLIST_KEYS.
const _REQUIRED_CHECKLIST_KEYS = [
  "regime_check",
  "risk_size_ok",
  "thesis_written",
  "exit_plan_defined",
  "invalidation_set",
  "correlation_check",
  "liquidity_check",
  "tax_impact_considered",
  "news_check",
  "regime_alignment",
] as const;

export function useCreateJournalEntry(): UseMutationResult<
  JournalEntry,
  unknown,
  { asset: string; direction: "BUY" | "HOLD" | "SELL"; pre_trade: PreTradeChecklist }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars) => {
      // Validate the rich UI checklist client-side, then translate it into the
      // backend's flat JournalEntryCreate contract: { symbol, direction, thesis,
      // pre_trade_checklist: {key: bool}, notes? }. The backend stores a plain
      // boolean map keyed by the 10 Appendix-B keys (NOT the rich object).
      const pt = PreTradeChecklistSchema.parse(vars.pre_trade);
      const checklist: Record<string, boolean> = {
        regime_check: pt.regime_alignment,
        risk_size_ok: pt.position_size_pct > 0 && pt.position_size_pct <= 100,
        thesis_written: pt.thesis.trim().length >= 10,
        exit_plan_defined:
          pt.stop_loss_pct != null || pt.invalidation.trim().length > 0,
        invalidation_set: pt.invalidation.trim().length > 0,
        correlation_check: pt.correlation_check,
        liquidity_check: pt.liquidity_check,
        tax_impact_considered: pt.tax_impact_considered,
        news_check: pt.news_check,
        regime_alignment: pt.regime_alignment,
      };
      const notes = [
        `Invalidation: ${pt.invalidation}`,
        `Size ${pt.position_size_pct}% · Horizon ${pt.time_horizon} · Conviction ${pt.conviction_score}/10`,
        pt.stop_loss_pct != null ? `Stop ${pt.stop_loss_pct}%` : null,
      ]
        .filter(Boolean)
        .join("\n");
      return apiFetch<JournalEntry>(`/journal/entries`, JournalEntrySchema, {
        method: "POST",
        body: {
          symbol: vars.asset,
          direction: vars.direction,
          thesis: pt.thesis,
          pre_trade_checklist: checklist,
          notes,
        },
        token,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}

export function useCloseJournalEntry(): UseMutationResult<
  JournalEntry,
  unknown,
  { id: string; post_mortem: PostMortem }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, post_mortem }) => {
      const pm = PostMortemSchema.parse(post_mortem);
      // Backend CloseRequest expects a free-text `post_mortem` string, not the
      // rich object. Serialise the structured form into markdown so the journal
      // stores a single, human-readable reflection (matches /journal/patterns,
      // which clusters on the post-mortem text).
      const markdown = [
        `**P&L**: ${pm.outcome_pnl_inr} INR (${pm.outcome_pnl_pct.toFixed(2)}%)`,
        `**Thesis correct**: ${pm.thesis_correct ? "yes" : "no"} · **Followed plan**: ${pm.followed_plan ? "yes" : "no"}`,
        `**What worked**: ${pm.what_worked}`,
        `**What didn't**: ${pm.what_didnt}`,
        `**Lessons**: ${pm.lessons}`,
        pm.next_actions ? `**Next actions**: ${pm.next_actions}` : null,
      ]
        .filter(Boolean)
        .join("\n\n");
      return apiFetch<JournalEntry>(
        `/journal/entries/${id}/close`,
        JournalEntrySchema,
        {
          method: "POST",
          body: { post_mortem: markdown },
          token,
        },
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}

/** Response from `GET /changes-today/`. */
export interface ChangesToday {
  window_hours: number;
  cutoff: string;
  signals: {
    symbol: string;
    direction: string;
    confidence: number;
    generated_at: string;
  }[];
  regime_flips: {
    symbol: string;
    from_regime: string | null;
    to_regime: string;
    since: string;
    confidence: number;
  }[];
  movers: {
    symbol: string;
    last_close: number;
    return_pct: number;
    z_score: number;
  }[];
  news: {
    title: string;
    source: string;
    impact_score: number;
    sentiment: number;
    published_at: string;
    url: string | null;
  }[];
}

const ChangesTodaySchema = z.object({
  window_hours: z.number(),
  cutoff: z.string(),
  signals: z.array(
    z.object({
      symbol: z.string(),
      direction: z.string(),
      confidence: z.number(),
      generated_at: z.string(),
    }),
  ),
  regime_flips: z.array(
    z.object({
      symbol: z.string(),
      from_regime: z.string().nullable(),
      to_regime: z.string(),
      since: z.string(),
      confidence: z.number(),
    }),
  ),
  movers: z.array(
    z.object({
      symbol: z.string(),
      last_close: z.number(),
      return_pct: z.number(),
      z_score: z.number(),
    }),
  ),
  news: z.array(
    z.object({
      title: z.string(),
      source: z.string(),
      impact_score: z.number(),
      sentiment: z.number(),
      published_at: z.string(),
      url: z.string().nullable(),
    }),
  ),
});

export function useChangesToday(
  opts: { hours?: number; zThreshold?: number; newsTop?: number } = {},
): UseQueryResult<ChangesToday> {
  const token = useAuthToken();
  const hours = opts.hours ?? 24;
  const z = opts.zThreshold ?? 5;
  const top = opts.newsTop ?? 5;
  return useQuery<ChangesToday>({
    queryKey: ["changes-today", { hours, z, top }],
    queryFn: () =>
      apiFetch<ChangesToday>(
        `/changes-today/?hours=${hours}&z_threshold=${z}&news_top=${top}`,
        ChangesTodaySchema,
        { token },
      ),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}

/** Response from `POST /journal/entries/{id}/auto_draft_post_mortem`. */
export interface AutoDraftPostMortem {
  draft_markdown: string;
  used_llm: boolean;
  routed_to: string;
}

const AutoDraftPostMortemSchema = z.object({
  draft_markdown: z.string(),
  used_llm: z.boolean(),
  routed_to: z.string(),
});

export function useAutoDraftPostMortem(): UseMutationResult<
  AutoDraftPostMortem,
  unknown,
  { id: string; realized_pnl_pct?: number | null; extra_context?: string | null }
> {
  const token = useAuthToken();
  return useMutation({
    mutationFn: ({ id, realized_pnl_pct, extra_context }) => {
      return apiFetch<AutoDraftPostMortem>(
        `/journal/entries/${id}/auto_draft_post_mortem`,
        AutoDraftPostMortemSchema,
        {
          method: "POST",
          body: {
            realized_pnl_pct: realized_pnl_pct ?? null,
            extra_context: extra_context ?? null,
          },
          token,
        },
      );
    },
  });
}

export type SupportedBroker =
  | "zerodha"
  | "icicidirect"
  | "groww"
  | "indmoney"
  | "vested"
  | "wazirx"
  | "coindcx"
  | "binance"
  | "coinbase"
  | "kraken";

export function useImportTaxCsv(): UseMutationResult<
  { imported: number; rejected: number; errors: string[] },
  unknown,
  { broker: SupportedBroker; file: File }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  const ResultSchema = z.object({
    imported: z.number().int(),
    rejected: z.number().int(),
    errors: z.array(z.string()).default([]),
  });
  return useMutation({
    mutationFn: ({ broker, file }) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiFetch(`/tax/import/${broker}`, ResultSchema, {
        method: "POST",
        body: fd,
        token,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tax"] }),
  });
}

// -----------------------------------------------------------------------------
// Derived / auxiliary endpoints (pair with backend `/api/v1/...`)
// -----------------------------------------------------------------------------

/**
 * Pairwise correlation matrix between top portfolio holdings.
 * Backend: `GET /portfolio/correlations`.
 * Shape: { symbols: string[], matrix: number[][] }
 */
export interface CorrelationMatrix {
  symbols: string[];
  matrix: number[][];
  window_days: number;
}

const CorrelationMatrixSchema = z.object({
  symbols: z.array(z.string()),
  matrix: z.array(z.array(z.number())),
  window_days: z.number().int().default(90),
});

export function useCorrelationMatrix(): UseQueryResult<CorrelationMatrix> {
  const token = useAuthToken();
  return useQuery<CorrelationMatrix>({
    queryKey: ["portfolio", "correlations"],
    queryFn: () =>
      apiFetch<CorrelationMatrix>(
        `/portfolio/correlations`,
        CorrelationMatrixSchema,
        { token },
      ),
    staleTime: 15 * 60_000,
  });
}

/** Historical VaR panel. Backend: `GET /portfolio/var`. */
export interface VarPanel {
  var_95_inr: number;
  var_99_inr: number;
  var_95_pct: number;
  var_99_pct: number;
  window_days: number;
  concentration_hhi: number;
  drawdown_series: Array<{ date: string; drawdown_pct: number }>;
  daily_new_positions_remaining: number;
  sharpe_30d: number;
  day_change_inr: number;
  day_change_pct: number;
}

const VarPanelSchema = z.object({
  var_95_inr: z.number(),
  var_99_inr: z.number(),
  var_95_pct: z.number(),
  var_99_pct: z.number(),
  window_days: z.number().int().default(90),
  concentration_hhi: z.number(),
  drawdown_series: z
    .array(
      z.object({
        date: z.string(),
        drawdown_pct: z.number(),
      }),
    )
    .default([]),
  daily_new_positions_remaining: z.number().int().default(0),
  sharpe_30d: z.number().default(0),
  day_change_inr: z.number().default(0),
  day_change_pct: z.number().default(0),
});

export function useVarPanel(): UseQueryResult<VarPanel> {
  const token = useAuthToken();
  return useQuery<VarPanel>({
    queryKey: ["portfolio", "var"],
    queryFn: () =>
      apiFetch<VarPanel>(`/portfolio/var`, VarPanelSchema, { token }),
    staleTime: 5 * 60_000,
  });
}

/** Calibration history per model. Backend: `GET /calibration/history`. */
export interface CalibrationHistoryPoint {
  evaluated_at: string;
  brier: number;
  ece: number;
}

export interface CalibrationHistory {
  model_name: string;
  model_version: string;
  points: CalibrationHistoryPoint[];
  suspended: boolean;
}

const CalibrationHistorySchema = z.object({
  model_name: z.string(),
  model_version: z.string(),
  points: z.array(
    z.object({
      evaluated_at: z.string(),
      brier: z.number(),
      ece: z.number(),
    }),
  ),
  suspended: z.boolean().default(false),
});

export function useCalibrationHistory(): UseQueryResult<CalibrationHistory[]> {
  const token = useAuthToken();
  return useQuery<CalibrationHistory[]>({
    queryKey: ["calibration", "history"],
    queryFn: () =>
      apiFetch<CalibrationHistory[]>(
        `/calibration/history`,
        z.array(CalibrationHistorySchema),
        { token },
      ),
    staleTime: 30 * 60_000,
  });
}

/**
 * Post-mortem auto-draft. Backend: `POST /agent/post-mortem` with body { entry_id }
 * Returns a pre-filled PostMortem the user can edit before saving.
 */
export function usePostMortemDraft(): UseMutationResult<
  PostMortem,
  unknown,
  { entry_id: string }
> {
  const token = useAuthToken();
  return useMutation({
    mutationFn: (vars) =>
      apiFetch<PostMortem>(`/agent/post-mortem`, PostMortemSchema, {
        method: "POST",
        body: vars,
        token,
      }),
  });
}

/**
 * Extended tax summary with 80C optimizer + surcharge info.
 * Backend: `GET /tax/details?fy=...`
 */
export interface TaxDetails {
  fy: string;
  slab_income_inr: number;
  eighty_c_used_inr: number;
  eighty_c_cap_inr: number;
  marginal_rate_pct: number;
  total_income_inr: number;
  old_regime_tax_inr: number;
  new_regime_tax_inr: number;
  surcharge_thresholds: Array<{ threshold_inr: number; rate_pct: number }>;
  form_67_lines: string[];
}

const TaxDetailsSchema = z.object({
  fy: z.string(),
  slab_income_inr: z.number().default(0),
  eighty_c_used_inr: z.number().default(0),
  eighty_c_cap_inr: z.number().default(150000),
  marginal_rate_pct: z.number().default(30),
  total_income_inr: z.number().default(0),
  old_regime_tax_inr: z.number().default(0),
  new_regime_tax_inr: z.number().default(0),
  surcharge_thresholds: z
    .array(z.object({ threshold_inr: z.number(), rate_pct: z.number() }))
    .default([
      { threshold_inr: 5_000_000, rate_pct: 10 },
      { threshold_inr: 10_000_000, rate_pct: 15 },
      { threshold_inr: 20_000_000, rate_pct: 25 },
      { threshold_inr: 50_000_000, rate_pct: 37 },
    ]),
  form_67_lines: z.array(z.string()).default([]),
});

export function useTaxDetails(fy?: string): UseQueryResult<TaxDetails> {
  const token = useAuthToken();
  return useQuery<TaxDetails>({
    queryKey: ["tax", "details", fy ?? "current"],
    queryFn: () => {
      const qs = fy ? `?fy=${fy}` : "";
      return apiFetch<TaxDetails>(`/tax/details${qs}`, TaxDetailsSchema, {
        token,
      });
    },
    staleTime: 30 * 60_000,
  });
}

/** Settings snapshot. Backend: `GET /settings`. */
export interface UserSettings {
  max_position_pct: number;
  drawdown_halt_pct: number;
  daily_new_positions_cap: number;
  tax_year: string;
  alert_severity_threshold: string;
  quiet_hours_start: string;
  quiet_hours_end: string;
  morning_brief_enabled: boolean;
  telegram_alerts_enabled: boolean;
  default_models_by_regime: Record<string, { name: string; version: string }>;
  scheduled_tasks: Array<{
    deployment: string;
    active: boolean;
    last_run_at: string | null;
  }>;
}

const UserSettingsSchema = z.object({
  max_position_pct: z.number().default(10),
  drawdown_halt_pct: z.number().default(20),
  daily_new_positions_cap: z.number().int().default(2),
  tax_year: z.string().default("2026-27"),
  alert_severity_threshold: z.string().default("warning"),
  quiet_hours_start: z.string().default("22:00"),
  quiet_hours_end: z.string().default("07:00"),
  morning_brief_enabled: z.boolean().default(true),
  telegram_alerts_enabled: z.boolean().default(false),
  default_models_by_regime: z
    .record(z.string(), z.object({ name: z.string(), version: z.string() }))
    .default({}),
  scheduled_tasks: z
    .array(
      z.object({
        deployment: z.string(),
        active: z.boolean(),
        last_run_at: z.string().nullable(),
      }),
    )
    .default([]),
});

export function useUserSettings(): UseQueryResult<UserSettings> {
  const token = useAuthToken();
  return useQuery<UserSettings>({
    queryKey: ["settings"],
    queryFn: () =>
      apiFetch<UserSettings>(`/settings`, UserSettingsSchema, { token }),
    staleTime: 5 * 60_000,
  });
}

export function useUpdateUserSettings(): UseMutationResult<
  UserSettings,
  unknown,
  Partial<UserSettings>
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch) =>
      apiFetch<UserSettings>(`/settings`, UserSettingsSchema, {
        method: "PATCH",
        body: patch,
        token,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

// -----------------------------------------------------------------------------
// Setup + source-health (Phase A: backend additions May 2026)
// -----------------------------------------------------------------------------

interface SetupStatus {
  time: string;
  counts: Record<string, number>;
  needs_setup: boolean;
  checklist: {
    watchlist_seeded: boolean;
    crypto_ingested: boolean;
    mf_ingested: boolean;
    fx_ingested: boolean;
    macro_ingested: boolean;
    news_ingested: boolean;
    holdings_added: boolean;
  };
}

// Backend: GET /setup/status (pfip/api/setup.py). `checklist` keys are
// fixed; `.passthrough()` tolerates any future additions without crashing.
const SetupChecklistSchema = z
  .object({
    watchlist_seeded: z.boolean(),
    crypto_ingested: z.boolean(),
    mf_ingested: z.boolean(),
    fx_ingested: z.boolean(),
    macro_ingested: z.boolean(),
    news_ingested: z.boolean(),
    holdings_added: z.boolean(),
  })
  .passthrough();

const SetupStatusSchema = z.object({
  time: z.string(),
  counts: z.record(z.string(), z.number()),
  needs_setup: z.boolean(),
  checklist: SetupChecklistSchema,
});

interface BootstrapResult {
  started_at: string;
  elapsed_seconds: number;
  ok: boolean;
  steps: Array<{ step: string; ok: boolean; rows?: number; added?: number; error?: string }>;
}

// Backend: POST /setup/bootstrap. Each step is `{step, ok, rows?|added?|error?}`.
const BootstrapStepSchema = z
  .object({
    step: z.string(),
    ok: z.boolean(),
    rows: z.number().optional(),
    added: z.number().optional(),
    error: z.string().optional(),
  })
  .passthrough();

const BootstrapResultSchema = z.object({
  started_at: z.string(),
  elapsed_seconds: z.number(),
  ok: z.boolean(),
  steps: z.array(BootstrapStepSchema),
});

// Backend: POST /setup/demo — `{ok, counts, note?}` on success,
// `{ok: false, error}` on failure. The consumer reads `result.counts`.
const SeedDemoResultSchema = z.object({
  ok: z.boolean(),
  counts: z.record(z.string(), z.number()).default({}),
  note: z.string().optional(),
  error: z.string().optional(),
});

// Backend: DELETE /setup/demo — `{ok, deleted}` on success,
// `{ok: false, error}` on failure.
const ClearDemoResultSchema = z.object({
  ok: z.boolean(),
  deleted: z.record(z.string(), z.number()).default({}),
  error: z.string().optional(),
});

/** One row of the source_health table as surfaced by `/health/sources`. */
export interface SourceHealth {
  source: string;
  last_run_at: string | null;
  last_success_at: string | null;
  last_rows: number | null;
  last_error: string | null;
  consecutive_failures: number;
  stale_seconds: number | null;
  status: "healthy" | "stale" | "failing" | "never_run";
}

/** Envelope returned by `GET /api/v1/health/sources`. */
export interface SourceHealthPayload {
  time: string;
  sources: SourceHealth[];
  summary:
    | { total: number; healthy: number; stale: number; failing: number }
    | { error: string };
}

// Backend: GET /health/sources (pfip/api/health.py). On a fresh install
// before migration 0006 the endpoint returns `summary: { error }` with an
// empty `sources` array; otherwise a per-adapter row + counts summary.
const SourceHealthRowSchema = z.object({
  source: z.string(),
  last_run_at: z.string().nullable(),
  last_success_at: z.string().nullable(),
  last_rows: z.number().nullable(),
  last_error: z.string().nullable(),
  consecutive_failures: z.number(),
  stale_seconds: z.number().nullable(),
  status: z.enum(["healthy", "stale", "failing", "never_run"]),
});

const SourceHealthPayloadSchema = z.object({
  time: z.string(),
  sources: z.array(SourceHealthRowSchema),
  summary: z.union([
    z.object({
      total: z.number(),
      healthy: z.number(),
      stale: z.number(),
      failing: z.number(),
    }),
    z.object({ error: z.string() }),
  ]),
});

/** GET /api/v1/setup/status — onboarding state for the welcome modal. */
export function useSetupStatus(opts?: { refetchInterval?: number }): UseQueryResult<SetupStatus> {
  const token = useAuthToken();
  return useQuery<SetupStatus>({
    queryKey: ["setup", "status"],
    queryFn: () =>
      apiFetch<SetupStatus>(`/setup/status`, SetupStatusSchema, {
        method: "GET",
        token,
      }),
    refetchInterval: opts?.refetchInterval ?? false,
    staleTime: 30_000,
  });
}

/** POST /api/v1/setup/bootstrap — one-button first-run (seed watchlist + initial ingests). */
export function useBootstrap(): UseMutationResult<BootstrapResult, ApiError, void> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation<BootstrapResult, ApiError, void>({
    mutationFn: () =>
      apiFetch<BootstrapResult>(`/setup/bootstrap`, BootstrapResultSchema, {
        method: "POST",
        body: {},
        token,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["setup", "status"] });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["candles"] });
    },
  });
}

/** POST /api/v1/setup/demo — synthetic seed for the dashboard. */
export function useSeedDemo(): UseMutationResult<{ ok: boolean; counts: Record<string, number> }, ApiError, void> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; counts: Record<string, number> }>(`/setup/demo`, SeedDemoResultSchema, {
        method: "POST",
        body: {},
        token,
      }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

/** DELETE /api/v1/setup/demo — remove demo rows. */
export function useClearDemo(): UseMutationResult<{ ok: boolean; deleted: Record<string, number> }, ApiError, void> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; deleted: Record<string, number> }>(`/setup/demo`, ClearDemoResultSchema, {
        method: "DELETE",
        token,
      }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

/** GET /api/v1/health/sources — per-adapter freshness. */
export function useSourceHealth(): UseQueryResult<SourceHealthPayload> {
  const token = useAuthToken();
  return useQuery<SourceHealthPayload>({
    queryKey: ["health", "sources"],
    queryFn: () =>
      apiFetch<SourceHealthPayload>(`/health/sources`, SourceHealthPayloadSchema, {
        method: "GET",
        token,
      }),
    refetchInterval: 60_000,
  });
}

// -----------------------------------------------------------------------------

/** Health check ping for network status indicator. */
export async function pingBackend(): Promise<boolean> {
  try {
    const resp = await fetch(`${API_BASE}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    return resp.ok;
  } catch {
    return false;
  }
}

/** Export tax package as PDF. Backend: `GET /tax/export?fy=...` */
export async function downloadTaxExport(
  fy: string,
  token: string | null,
): Promise<Blob> {
  const resp = await fetch(`${API_BASE}/tax/export?fy=${fy}`, {
    headers: {
      Accept: "application/pdf",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!resp.ok) throw new ApiError("Export failed", resp.status, null);
  return resp.blob();
}
