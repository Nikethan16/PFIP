"use client";

/**
 * Operations · Schedules — lists every registered Prefect deployment
 * with its cron expression, last run, last success, and how stale it
 * is right now. Pages Telegram if anything is overdue (handled by the
 * `skipped_task_alerter` hourly flow).
 *
 * Backend: `GET /api/v1/schedules`.
 */

import { AlertTriangle, CheckCircle2, Clock } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { useSchedules, type ScheduleRow } from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

const BUDGET_HOURS: Record<string, number> = {
  "ingest-news-15min": 1,
  "ingest-btc-daily": 48,
  "compute-features-btc-daily": 48,
  "anomaly-scan-daily": 48,
  "regime-detect-btc-daily": 48,
  "reconcile-daily": 48,
  "market-close-summary": 48,
  "weekly-review": 192,
  "ragas-eval-monthly": 840,
  "shadow-rollup-monthly": 840,
  "annual-itr-drill": 9600,
  "skipped-task-alerter": 4,
};

function staleness(row: ScheduleRow): "ok" | "stale" | "never" {
  if (row.age_hours == null) return "never";
  const budget = BUDGET_HOURS[row.name] ?? 24;
  return row.age_hours > budget ? "stale" : "ok";
}

export default function SchedulesPage() {
  const { data, isLoading, error } = useSchedules();

  return (
    <div className="space-y-4">
      <PageHeader
        title="Schedules"
        description="Every Prefect deployment. Auto-refreshes every 60 seconds. Overdue rows page Telegram via the skipped-task watchdog."
      />

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load schedules: {(error as Error).message}
        </div>
      ) : data?.error ? (
        <EmptyState
          title="Prefect not reachable"
          description={`The schedules API couldn't reach the Prefect server (${data.error}). Start Prefect (\`docker compose up prefect\`) and refresh.`}
        />
      ) : !data?.deployments.length ? (
        <EmptyState
          title="No deployments registered"
          description="Run `python -m pfip.prefect.deploy` inside the backend container to register the standard set of flows."
        />
      ) : (
        <SchedulesTable rows={data.deployments} />
      )}
    </div>
  );
}

function SchedulesTable({ rows }: { rows: ScheduleRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Name</th>
            <th className="px-3 py-2 text-left font-medium">Cron</th>
            <th className="px-3 py-2 text-left font-medium">Tags</th>
            <th className="px-3 py-2 text-left font-medium">Last run</th>
            <th className="px-3 py-2 text-left font-medium">Last success</th>
            <th className="px-3 py-2 text-right font-medium">Age (h)</th>
            <th className="px-3 py-2 text-left font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const s = staleness(r);
            return (
              <tr key={r.name} className="border-t hover:bg-accent/40 transition-colors">
                <td className="px-3 py-2 font-mono text-xs">{r.name}</td>
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                  {r.cron ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {r.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded-full border px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {r.last_run_at ? formatIST(r.last_run_at) : "—"}
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {r.last_success_at ? formatIST(r.last_success_at) : "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {r.age_hours == null ? "—" : r.age_hours.toFixed(1)}
                </td>
                <td className="px-3 py-2">
                  <StatusPill status={s} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StatusPill({ status }: { status: "ok" | "stale" | "never" }) {
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3" />
        On time
      </span>
    );
  }
  if (status === "stale") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
        <AlertTriangle className="h-3 w-3" />
        Overdue
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
      <Clock className="h-3 w-3" />
      Never run
    </span>
  );
}
