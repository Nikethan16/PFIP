"use client";

/**
 * Sahara "Backtest Lab" — walk-forward + CPCV backtest runs.
 *
 * A read-only ledger of the engine's persisted walk-forward backtests. Each row
 * is one run (symbol + strategy) with its headline risk-adjusted numbers; click
 * a row to open a detail panel with fold-by-fold metrics and the strategy-vs
 * buy-&-hold benchmark.
 *
 * Data mapping (every value traces to a real hook — no fabrication):
 *   - run list            ← useBacktestRuns()      (/backtest/runs)
 *   - per-run detail      ← useBacktestRun(id)      (/backtest/runs/{id})
 *   - fold metrics        ← metrics.walkforward.fold_metrics
 *   - benchmark compare   ← metrics.benchmarks {buy_hold, strategy, …}
 *   - Monte-Carlo / shuffle / params ← metrics.monte_carlo / shuffle_test / params
 *
 * The `⚠ shuffle-test flag` on a row means lookahead_ok=false — that run did NOT
 * pass the engine's look-ahead (shuffle) guard, so its edge may be spurious.
 * ADVISORY-ONLY: historical simulation, never a recommendation or an order.
 */

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  FlaskConical,
  Layers,
  MessageSquareText,
  ShieldCheck,
  X,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import {
  useBacktestRun,
  useBacktestRuns,
  type BacktestBenchmarkLeg,
  type BacktestFoldMetric,
  type BacktestRunSummary,
} from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

// --- formatting helpers ------------------------------------------------------

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

/** A 0..1 fraction → signed percentage string (e.g. -0.224 → "-22.5%"). */
function fmtFracPct(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function sharpeTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "text-muted-foreground";
  return v > 0
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-red-700 dark:text-red-400";
}

// --- Page --------------------------------------------------------------------

export default function BacktestPage() {
  const { data, isLoading, error } = useBacktestRuns();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  return (
    <div className="space-y-6">
      {/* Header — serif "Backtest Lab" + advisory eyebrow. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Walk-forward // out-of-sample · advisory only
            <FreshnessBadge sources={["backtest_walk_forward"]} />
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Backtest Lab
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Walk-forward + CPCV simulations from the strategy engine — Sharpe,
            drawdown, hit-rate and fold stability, scored strictly out-of-sample.
            Historical simulation only, never a recommendation.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load backtest runs: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={FlaskConical}
            title="No backtest runs yet"
            description="Walk-forward backtests are produced out-of-band by the backtest engine. Once the backtest-walk-forward flow runs, every simulation will appear here with its fold-by-fold metrics."
          />
        </section>
      ) : (
        <RunsTable
          runs={data}
          selectedId={selectedId}
          onSelect={(id) => setSelectedId((cur) => (cur === id ? null : id))}
        />
      )}

      {/* Detail drawer — fold metrics + benchmark for the selected run. */}
      <RunDetailDrawer
        runId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}

// --- Runs table --------------------------------------------------------------

function RunsTable({
  runs,
  selectedId,
  onSelect,
}: {
  runs: BacktestRunSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="border border-border/60 bg-card">
      <div className="flex items-center justify-between border-b border-border/40 p-5">
        <div>
          <div className="eyebrow">Runs ledger</div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            {runs.length} backtest{runs.length === 1 ? "" : "s"} · newest first
          </h3>
        </div>
      </div>

      {/* Column header — hidden on small screens; cards stack instead. */}
      <div className="hidden grid-cols-12 gap-3 border-b border-border/40 px-5 py-2.5 font-label text-[10px] uppercase tracking-wider text-muted-foreground md:grid">
        <div className="col-span-3">Market · strategy</div>
        <div className="col-span-2 text-right">Sharpe</div>
        <div className="col-span-2 text-right">Max DD</div>
        <div className="col-span-1 text-right">Hit</div>
        <div className="col-span-1 text-right">Folds</div>
        <div className="col-span-3 text-right">Window</div>
      </div>

      <div className="divide-y divide-border/40">
        {runs.map((r) => (
          <RunRow
            key={r.id}
            run={r}
            active={selectedId === r.id}
            onSelect={() => onSelect(r.id)}
          />
        ))}
      </div>
    </section>
  );
}

function RunRow({
  run,
  active,
  onSelect,
}: {
  run: BacktestRunSummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-expanded={active}
      className={cn(
        "grid w-full grid-cols-2 items-center gap-3 px-5 py-3 text-left transition-colors hover-tile md:grid-cols-12",
        active && "bg-accent/40",
      )}
    >
      {/* Market + strategy + look-ahead flag */}
      <div className="col-span-2 min-w-0 md:col-span-3">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-sm font-semibold">
            {run.market}
          </span>
          <LookaheadFlag ok={run.lookahead_ok} />
        </div>
        <div className="mt-0.5 truncate font-label text-[11px] uppercase tracking-wider text-muted-foreground">
          {run.strategy}
          {run.model_name ? ` · ${run.model_name}` : ""}
        </div>
      </div>

      {/* Sharpe (coloured) */}
      <Metric
        className="md:col-span-2"
        label="Sharpe"
        value={fmtNum(run.sharpe)}
        tone={sharpeTone(run.sharpe)}
      />

      {/* Max drawdown as % */}
      <Metric
        className="md:col-span-2"
        label="Max DD"
        value={fmtFracPct(run.max_drawdown)}
        tone="text-red-700 dark:text-red-400"
      />

      {/* Hit rate */}
      <Metric
        className="md:col-span-1"
        label="Hit"
        value={run.hit_rate != null ? fmtFracPct(run.hit_rate, 0) : "—"}
      />

      {/* Folds */}
      <Metric
        className="md:col-span-1"
        label="Folds"
        value={run.n_folds != null ? String(run.n_folds) : "—"}
      />

      {/* Window / date */}
      <div className="col-span-2 flex items-center justify-between gap-2 md:col-span-3 md:justify-end">
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
          {run.start_date && run.end_date
            ? `${run.start_date} → ${run.end_date}`
            : run.created_at
              ? formatIST(run.created_at, "dd MMM yyyy")
              : "—"}
        </span>
        <ArrowRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            active && "translate-x-0.5 text-primary",
          )}
          aria-hidden
        />
      </div>
    </button>
  );
}

function Metric({
  label,
  value,
  tone,
  className,
}: {
  label: string;
  value: string;
  tone?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between md:block md:text-right", className)}>
      <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground md:hidden">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-sm font-semibold tabular-nums",
          tone ?? "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** Subtle "passed / shuffle-test flag" chip for the engine's look-ahead guard. */
function LookaheadFlag({ ok }: { ok: boolean }) {
  if (ok) {
    return (
      <span
        className="inline-flex shrink-0 items-center gap-1 border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 font-label text-[9px] uppercase tracking-wider text-emerald-700 dark:text-emerald-300"
        title="Passed the engine's look-ahead (shuffle) guard."
      >
        <ShieldCheck className="h-2.5 w-2.5" aria-hidden />
        Guard OK
      </span>
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-label text-[9px] uppercase tracking-wider text-amber-700 dark:text-amber-300"
      title="This run did NOT pass the engine's look-ahead (shuffle) guard — its edge may be spurious. Treat with caution."
    >
      <AlertTriangle className="h-2.5 w-2.5" aria-hidden />
      Shuffle-test flag
    </span>
  );
}

// --- Run detail drawer -------------------------------------------------------

function RunDetailDrawer({
  runId,
  onClose,
}: {
  runId: string | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useBacktestRun(runId);
  const open = runId != null;

  // Close on Escape.
  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-foreground/20 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Backtest run detail"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-border/70 bg-card shadow-xl">
        {/* Drawer header */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border/50 bg-card/95 p-5 backdrop-blur">
          <div className="min-w-0">
            <div className="eyebrow">Backtest detail</div>
            <h2 className="mt-1 truncate font-serif text-2xl tracking-tight">
              {data ? data.market : "Loading…"}
            </h2>
            {data ? (
              <p className="mt-0.5 font-label text-[11px] uppercase tracking-wider text-muted-foreground">
                {data.strategy}
                {data.model_name ? ` · ${data.model_name}` : ""}
                {data.start_date && data.end_date
                  ? ` · ${data.start_date} → ${data.end_date}`
                  : ""}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close detail"
            className="-mr-1 shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-6 p-5">
          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : error ? (
            <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
              Couldn&apos;t load this run: {(error as Error).message}
            </div>
          ) : data ? (
            <>
              {/* Headline metric grid */}
              <HeadlineGrid run={data} />

              {/* Look-ahead / shuffle-test status callout */}
              <ShuffleCallout
                ok={data.lookahead_ok}
                shuffle={data.metrics.shuffle_test ?? null}
              />

              {/* Strategy vs buy-&-hold benchmark */}
              <BenchmarkTable
                benchmarks={data.metrics.benchmarks ?? null}
              />

              {/* Fold-by-fold walk-forward metrics */}
              <FoldTable
                folds={data.metrics.walkforward?.fold_metrics ?? []}
              />

              {/* Engine params footnote */}
              <ParamsFootnote params={data.params} />

              <div className="flex items-center justify-end border-t border-border/40 pt-4">
                <Link
                  href={"/chat" as never}
                  className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 font-label text-[11px] uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
                >
                  <MessageSquareText className="h-3.5 w-3.5" />
                  Ask the analyst about this run
                </Link>
              </div>
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function HeadlineGrid({ run }: { run: BacktestRunSummary }) {
  const cells: Array<{ label: string; value: string; tone?: string }> = [
    { label: "Sharpe", value: fmtNum(run.sharpe), tone: sharpeTone(run.sharpe) },
    { label: "Sortino", value: fmtNum(run.sortino), tone: sharpeTone(run.sortino) },
    {
      label: "Max drawdown",
      value: fmtFracPct(run.max_drawdown),
      tone: "text-red-700 dark:text-red-400",
    },
    { label: "Calmar", value: fmtNum(run.calmar), tone: sharpeTone(run.calmar) },
    {
      label: "Hit rate",
      value: run.hit_rate != null ? fmtFracPct(run.hit_rate, 0) : "—",
    },
    { label: "CAGR", value: fmtFracPct(run.cagr), tone: sharpeTone(run.cagr) },
    {
      label: "Total return",
      value: fmtFracPct(run.total_return),
      tone: sharpeTone(run.total_return),
    },
    { label: "Trades", value: run.n_trades != null ? String(run.n_trades) : "—" },
    {
      label: "CPCV Sharpe",
      value: fmtNum(run.cpcv_mean_sharpe),
      tone: sharpeTone(run.cpcv_mean_sharpe),
    },
  ];
  return (
    <div className="grid grid-cols-3 gap-px overflow-hidden border border-border/50 bg-border/50">
      {cells.map((c) => (
        <div key={c.label} className="bg-card p-3">
          <div className="eyebrow">{c.label}</div>
          <div
            className={cn(
              "mt-0.5 font-mono text-base font-semibold tabular-nums",
              c.tone ?? "text-foreground",
            )}
          >
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function ShuffleCallout({
  ok,
  shuffle,
}: {
  ok: boolean;
  shuffle: {
    ok?: boolean;
    original_sharpe?: number;
    shuffled_mean_sharpe?: number;
    shuffled_max_sharpe?: number;
    n_shuffles?: number;
  } | null;
}) {
  return (
    <div
      className={cn(
        "border p-4",
        ok
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-amber-500/30 bg-amber-500/5",
      )}
    >
      <div className="flex items-center gap-2">
        {ok ? (
          <ShieldCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        )}
        <span className="font-label text-[11px] uppercase tracking-wider text-foreground">
          {ok ? "Passed look-ahead guard" : "Shuffle-test flag"}
        </span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {ok
          ? "The shuffle (look-ahead) test passed: the strategy's edge did not survive on time-shuffled data, which is the expected, healthy result — it suggests the signal isn't an artefact of look-ahead leakage."
          : "This run did NOT pass the engine's look-ahead guard. On time-shuffled data the strategy still scored as well or better, which is a red flag that the apparent edge may be spurious. Treat these numbers with caution."}
      </p>
      {shuffle ? (
        <div className="mt-3 grid grid-cols-3 gap-3 border-t border-border/30 pt-3 text-center">
          <div>
            <div className="eyebrow">Original Sharpe</div>
            <div className={cn("mt-0.5 font-mono text-sm font-semibold tabular-nums", sharpeTone(shuffle.original_sharpe ?? null))}>
              {fmtNum(shuffle.original_sharpe ?? null)}
            </div>
          </div>
          <div>
            <div className="eyebrow">Shuffled mean</div>
            <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums">
              {fmtNum(shuffle.shuffled_mean_sharpe ?? null)}
            </div>
          </div>
          <div>
            <div className="eyebrow">Shuffled max</div>
            <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums">
              {fmtNum(shuffle.shuffled_max_sharpe ?? null)}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BenchmarkTable({
  benchmarks,
}: {
  benchmarks: Record<string, BacktestBenchmarkLeg> | null;
}) {
  // Prefer the canonical strategy-vs-buy&hold pair; fall back to whatever keys
  // the engine emitted. `strategy` and `buy_hold` always lead when present.
  const entries = React.useMemo(() => {
    if (!benchmarks) return [];
    const keys = Object.keys(benchmarks);
    const ordered = [
      ...["strategy", "buy_hold"].filter((k) => keys.includes(k)),
      ...keys.filter((k) => k !== "strategy" && k !== "buy_hold"),
    ];
    return ordered.map((k) => [k, benchmarks[k]!] as const);
  }, [benchmarks]);

  if (!entries.length) {
    return null;
  }

  const LABELS: Record<string, string> = {
    strategy: "Strategy",
    buy_hold: "Buy & hold",
  };

  return (
    <div>
      <h4 className="eyebrow mb-2 flex items-center gap-1.5">
        <Layers className="h-3 w-3" />
        Strategy vs buy &amp; hold
      </h4>
      <div className="overflow-x-auto border border-border/50">
        <table className="w-full text-right text-xs">
          <thead>
            <tr className="border-b border-border/40 bg-secondary/40 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">Leg</th>
              <th className="px-3 py-2 font-medium">Sharpe</th>
              <th className="px-3 py-2 font-medium">Sortino</th>
              <th className="px-3 py-2 font-medium">Calmar</th>
              <th className="px-3 py-2 font-medium">Max DD</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {entries.map(([key, leg]) => (
              <tr key={key} className={cn(key === "strategy" && "bg-primary/5")}>
                <td className="px-3 py-2 text-left font-label text-[11px] uppercase tracking-wider text-foreground">
                  {LABELS[key] ?? key.replace(/_/g, " ")}
                </td>
                <td className={cn("px-3 py-2 font-mono tabular-nums", sharpeTone(leg.sharpe))}>
                  {fmtNum(leg.sharpe)}
                </td>
                <td className={cn("px-3 py-2 font-mono tabular-nums", sharpeTone(leg.sortino))}>
                  {fmtNum(leg.sortino)}
                </td>
                <td className={cn("px-3 py-2 font-mono tabular-nums", sharpeTone(leg.calmar))}>
                  {fmtNum(leg.calmar)}
                </td>
                <td className="px-3 py-2 font-mono tabular-nums text-red-700 dark:text-red-400">
                  {fmtFracPct(leg.max_drawdown)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FoldTable({ folds }: { folds: BacktestFoldMetric[] }) {
  return (
    <div>
      <h4 className="eyebrow mb-2">Fold-by-fold · walk-forward</h4>
      {!folds.length ? (
        <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
          No per-fold metrics recorded for this run.
        </div>
      ) : (
        <div className="overflow-x-auto border border-border/50">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-border/40 bg-secondary/40 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">Fold</th>
                <th className="px-3 py-2 font-medium">Sharpe</th>
                <th className="px-3 py-2 font-medium">Max DD</th>
                <th className="px-3 py-2 font-medium">Hit</th>
                <th className="px-3 py-2 font-medium">Avg ret</th>
                <th className="px-3 py-2 font-medium">Trades</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {folds.map((f) => (
                <tr key={f.fold}>
                  <td className="px-3 py-1.5 text-left font-mono tabular-nums text-muted-foreground">
                    #{f.fold}
                  </td>
                  <td className={cn("px-3 py-1.5 font-mono tabular-nums", sharpeTone(f.sharpe))}>
                    {fmtNum(f.sharpe)}
                  </td>
                  <td className="px-3 py-1.5 font-mono tabular-nums text-red-700 dark:text-red-400">
                    {fmtFracPct(f.max_drawdown)}
                  </td>
                  <td className="px-3 py-1.5 font-mono tabular-nums">
                    {f.hit_rate != null ? fmtFracPct(f.hit_rate, 0) : "—"}
                  </td>
                  <td className={cn("px-3 py-1.5 font-mono tabular-nums", sharpeTone(f.avg_return))}>
                    {f.avg_return != null ? fmtFracPct(f.avg_return, 2) : "—"}
                  </td>
                  <td className="px-3 py-1.5 font-mono tabular-nums text-muted-foreground">
                    {f.n_trades ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ParamsFootnote({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params).filter(
    ([, v]) => typeof v === "string" || typeof v === "number" || typeof v === "boolean",
  );
  if (!entries.length) return null;
  return (
    <div className="border-t border-border/40 pt-4">
      <h4 className="eyebrow mb-2">Engine parameters</h4>
      <div className="flex flex-wrap gap-2">
        {entries.map(([k, v]) => (
          <span
            key={k}
            className="inline-flex items-center gap-1.5 border border-border/50 bg-secondary/30 px-2 py-1 font-mono text-[11px] text-muted-foreground"
          >
            <span className="text-foreground/70">{k}</span>
            <span className="tabular-nums">{String(v)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
