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
  ScheduleFARowSchema,
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
  type Signal,
  type TaxSummary,
  type WatchlistItem,
} from "./contracts";

// -----------------------------------------------------------------------------
// Core fetch wrapper
// -----------------------------------------------------------------------------

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

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
    // Token expired or invalid — drop session and let the route guard handle it.
    await signOut({ redirect: false });
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
  { symbol: string; label?: string }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars) =>
      apiFetch<WatchlistItem>(`/watchlist`, WatchlistItemSchema, {
        method: "POST",
        body: vars,
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

export function useMorningBrief(date?: string): UseQueryResult<MorningBrief> {
  const token = useAuthToken();
  return useQuery<MorningBrief>({
    queryKey: ["morning-brief", date ?? "today"],
    queryFn: () => {
      const qs = date ? `?date=${date}` : "";
      return apiFetch<MorningBrief>(
        `/agent/morning-brief${qs}`,
        MorningBriefSchema,
        { token },
      );
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
      const qs = fy ? `?fy=${fy}` : "";
      return apiFetch<TaxSummary>(`/tax/summary${qs}`, TaxSummarySchema, {
        token,
      });
    },
    staleTime: 10 * 60_000,
  });
}

export function useScheduleFA(fy?: string): UseQueryResult<ScheduleFARow[]> {
  const token = useAuthToken();
  return useQuery<ScheduleFARow[]>({
    queryKey: ["tax", "schedule-fa", fy ?? "current"],
    queryFn: () => {
      const qs = fy ? `?fy=${fy}` : "";
      return apiFetch<ScheduleFARow[]>(
        `/tax/schedule-fa${qs}`,
        z.array(ScheduleFARowSchema),
        { token },
      );
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

export function useCreateJournalEntry(): UseMutationResult<
  JournalEntry,
  unknown,
  { asset: string; direction: "BUY" | "HOLD" | "SELL"; pre_trade: PreTradeChecklist }
> {
  const token = useAuthToken();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars) => {
      // Validate the checklist client-side before firing the request.
      PreTradeChecklistSchema.parse(vars.pre_trade);
      return apiFetch<JournalEntry>(`/journal/entries`, JournalEntrySchema, {
        method: "POST",
        body: vars,
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
      PostMortemSchema.parse(post_mortem);
      return apiFetch<JournalEntry>(
        `/journal/entries/${id}/close`,
        JournalEntrySchema,
        {
          method: "POST",
          body: { post_mortem },
          token,
        },
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
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
