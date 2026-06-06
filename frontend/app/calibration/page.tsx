"use client";

/**
 * Sahara "Calibration" — the model-reliability page.
 *
 * Are the model's stated probabilities honest? This page reports Brier / ECE /
 * sharpness per pinned model with reliability curves, and tracks ECE over time.
 *
 * Data mapping (every value traces to a real hook — no fabrication):
 *   - report list / diagrams ← useCalibration()        (/calibration/latest)
 *   - KPI strip (Brier/ECE/n) ← the most-recent report in that list
 *   - per-model history series ← useCalibrationHistory() (/calibration/history)
 *
 * IMPORTANT: calibration reports are produced MONTHLY, and only once signals
 * have realised outcomes to score against. Until then the list is empty and the
 * page renders an honest, intentional empty state rather than fabricated bins.
 */

import * as React from "react";
import { Activity, ShieldAlert, Target } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { ReliabilityCard } from "@/components/calibration/reliability-card";
import { Kpi } from "@/components/shared/kpi";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import {
  useCalibration,
  useCalibrationHistory,
  type CalibrationHistory,
} from "@/lib/api";
import type { CalibrationReport } from "@/lib/contracts";
import { formatIST } from "@/lib/utils";

/** Most-recent report by created_at (fall back to first when undated). */
function pickLatest(reports: CalibrationReport[]): CalibrationReport | null {
  if (!reports.length) return null;
  return [...reports].sort((a, b) => {
    const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
    const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
    return tb - ta;
  })[0]!;
}

export default function CalibrationPage() {
  const { data, isLoading, error } = useCalibration();
  const { data: history } = useCalibrationHistory();

  const historyByKey = React.useMemo(() => {
    const map = new Map<string, CalibrationHistory>();
    (history ?? []).forEach((h) =>
      map.set(`${h.model_name}@${h.model_version}`, h),
    );
    return map;
  }, [history]);

  const latest = React.useMemo(() => pickLatest(data ?? []), [data]);
  const suspendedCount = React.useMemo(() => {
    return (data ?? []).filter((r) => {
      const h = historyByKey.get(`${r.model_name}@${r.model_version}`);
      return h?.suspended ?? r.ece > 0.15;
    }).length;
  }, [data, historyByKey]);

  return (
    <div className="space-y-8">
      {/* Header — serif "Calibration" + advisory eyebrow. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Model reliability // lower is better
            <FreshnessBadge sources={["calibration_daily"]} />
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Calibration
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Brier, ECE and sharpness per model with reliability curves. A model
            is auto-suspended (flagged red) when its ECE stays above 0.15 for two
            consecutive months.
          </p>
        </div>
      </div>

      {/* KPI strip — latest report's headline scores. */}
      {isLoading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load calibration: {(error as Error).message}
        </div>
      ) : latest ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Kpi
            label="Brier · latest"
            accent
            value={latest.brier.toFixed(3)}
            valueClassName="text-primary"
            hint={latest.brier <= 0.15 ? "sharp" : latest.brier <= 0.25 ? "ok" : "loose"}
            icon={<Target className="h-3.5 w-3.5" />}
          />
          <Kpi
            label="ECE · latest"
            value={latest.ece.toFixed(3)}
            tone={latest.ece <= 0.05 ? "up" : latest.ece <= 0.1 ? "neutral" : "down"}
            hint={latest.ece > 0.15 ? "over limit" : "within 0.15"}
            icon={<Activity className="h-3.5 w-3.5" />}
          />
          <Kpi
            label="Samples"
            value={latest.n_samples.toLocaleString()}
            hint={`${latest.model_name} v${latest.model_version}`}
          />
          <Kpi
            label="Suspended"
            value={String(suspendedCount)}
            tone={suspendedCount > 0 ? "down" : "up"}
            hint={`${(data ?? []).length} model${(data ?? []).length === 1 ? "" : "s"} tracked`}
            icon={<ShieldAlert className="h-3.5 w-3.5" />}
          />
        </div>
      ) : null}

      {/* Reliability cards (diagram + ECE history per model). */}
      {isLoading ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-96 w-full" />
          ))}
        </div>
      ) : error ? null : !data?.length ? (
        <CalibrationEmptyState />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {data.map((rpt) => (
            <ReliabilityCard
              key={`${rpt.model_name}-${rpt.model_version}`}
              report={rpt}
              history={historyByKey.get(
                `${rpt.model_name}@${rpt.model_version}`,
              )}
            />
          ))}
        </div>
      )}

      {/* Calibration-over-time — the history series per model. */}
      <CalibrationHistoryBlock history={history ?? []} />
    </div>
  );
}

// --- Empty state (calibration produced monthly) -----------------------------

function CalibrationEmptyState() {
  return (
    <section className="border border-border/60 bg-card">
      <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-secondary/50 text-muted-foreground">
          <Target className="h-5 w-5" aria-hidden />
        </div>
        <div className="max-w-md space-y-2">
          <h2 className="font-serif text-2xl tracking-tight">
            No calibration reports yet
          </h2>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Reports are produced{" "}
            <span className="text-foreground">monthly</span>, and only once
            issued signals have realised outcomes to score against. The first
            reliability curve will appear here automatically after a calibration
            run completes — no action needed.
          </p>
        </div>
        <div className="flex items-center gap-2 border-t border-border/40 pt-4 font-mono text-[11px] text-muted-foreground">
          <Activity className="h-3.5 w-3.5 text-primary" />
          Brier &amp; ECE · lower is better.
        </div>
      </div>
    </section>
  );
}

// --- Calibration history (ECE / Brier over time) ----------------------------

/**
 * Per-model history block. Backed by useCalibrationHistory(); each model gets a
 * compact row of its latest evaluated point plus a count of how many points
 * exist. Empty until at least one calibration run has been recorded.
 */
function CalibrationHistoryBlock({
  history,
}: {
  history: CalibrationHistory[];
}) {
  const withPoints = history.filter((h) => h.points.length > 0);

  return (
    <section className="border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow">Track record</div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">
          Calibration over time
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Month-over-month Brier &amp; ECE per model. Two consecutive months
          above the 0.15 ECE limit auto-suspends a model.
        </p>
      </div>
      <div className="p-5">
        {!withPoints.length ? (
          <p className="text-xs text-muted-foreground">
            No history recorded yet. Each monthly calibration run appends a point
            here, building the trend that drives auto-suspension.
          </p>
        ) : (
          <div className="divide-y divide-border/40 border border-border/50">
            <div className="hidden grid-cols-12 gap-2 bg-secondary/30 px-3 py-2 font-label text-[10px] uppercase tracking-wider text-muted-foreground sm:grid">
              <span className="col-span-4">Model</span>
              <span className="col-span-2 text-right">Latest Brier</span>
              <span className="col-span-2 text-right">Latest ECE</span>
              <span className="col-span-2 text-right">Points</span>
              <span className="col-span-2 text-right">Status</span>
            </div>
            {withPoints.map((h) => {
              const last = h.points[h.points.length - 1]!;
              return (
                <div
                  key={`${h.model_name}@${h.model_version}`}
                  className="grid grid-cols-2 gap-2 px-3 py-2.5 text-sm sm:grid-cols-12"
                >
                  <div className="sm:col-span-4">
                    <div className="font-medium">{h.model_name}</div>
                    <div className="font-mono text-[10px] uppercase text-muted-foreground">
                      v{h.model_version} · {formatIST(last.evaluated_at, "dd MMM yyyy")}
                    </div>
                  </div>
                  <div className="font-mono text-xs tabular-nums sm:col-span-2 sm:text-right">
                    {last.brier.toFixed(3)}
                  </div>
                  <div className="font-mono text-xs tabular-nums sm:col-span-2 sm:text-right">
                    {last.ece.toFixed(3)}
                  </div>
                  <div className="font-mono text-xs text-muted-foreground tabular-nums sm:col-span-2 sm:text-right">
                    {h.points.length}
                  </div>
                  <div className="sm:col-span-2 sm:text-right">
                    <span
                      className={
                        h.suspended
                          ? "font-label text-[10px] uppercase tracking-wider text-red-700 dark:text-red-400"
                          : "font-label text-[10px] uppercase tracking-wider text-emerald-700 dark:text-emerald-400"
                      }
                    >
                      {h.suspended ? "Suspended" : "Active"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
