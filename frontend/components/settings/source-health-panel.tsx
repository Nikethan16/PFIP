"use client";

/**
 * Source health panel for the Settings page. Polls
 * `GET /api/v1/health/sources` every 60s and renders a table of every
 * ingest adapter with last-run timestamp, row count, and status badge.
 *
 * Powered by data the ingest layer writes to `source_health` via
 * `pfip.ingest._common.source_health.record_run`. If an adapter hasn't
 * run yet, it's omitted from the table.
 */

import { Loader2, AlertTriangle, CheckCircle2, Clock, Circle } from "lucide-react";
import { useSourceHealth } from "@/lib/api";

type Status = "healthy" | "stale" | "failing" | "never_run";

function StatusBadge({ status }: { status: Status }) {
  const cfg = {
    healthy: { Icon: CheckCircle2, color: "text-green-600 dark:text-green-400", label: "Healthy" },
    stale: { Icon: Clock, color: "text-yellow-600 dark:text-yellow-400", label: "Stale" },
    failing: { Icon: AlertTriangle, color: "text-red-600 dark:text-red-400", label: "Failing" },
    never_run: { Icon: Circle, color: "text-muted-foreground", label: "Never run" },
  }[status];
  const { Icon, color, label } = cfg;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${color}`}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

function formatTimeAgo(iso: string | null): string {
  if (!iso) return "never";
  const ts = new Date(iso).getTime();
  const diff = Date.now() - ts;
  if (diff < 60_000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  return `${Math.round(diff / 86_400_000)}d ago`;
}

export function SourceHealthPanel() {
  const query = useSourceHealth();

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground p-4">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading source health…
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="text-sm text-destructive p-4">
        Failed to load source health: {(query.error as Error).message}
      </div>
    );
  }

  const data = query.data;
  if (!data || data.sources.length === 0) {
    return (
      <div className="text-sm text-muted-foreground p-4">
        No source-health rows yet. Run an ingest flow first
        (<code>docker exec pfip-backend python -m pfip.prefect.flows.ingest_fx_daily</code>)
        and refresh.
      </div>
    );
  }

  const summary = "total" in data.summary ? data.summary : null;

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-lg border border-border p-3">
            <div className="text-xs text-muted-foreground">Total adapters</div>
            <div className="text-2xl font-semibold font-num mt-1">{summary.total}</div>
          </div>
          <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-3">
            <div className="text-xs text-green-700 dark:text-green-300">Healthy</div>
            <div className="text-2xl font-semibold font-num mt-1 text-green-700 dark:text-green-400">{summary.healthy}</div>
          </div>
          <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3">
            <div className="text-xs text-yellow-700 dark:text-yellow-300">Stale</div>
            <div className="text-2xl font-semibold font-num mt-1 text-yellow-700 dark:text-yellow-400">{summary.stale}</div>
          </div>
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
            <div className="text-xs text-red-700 dark:text-red-300">Failing</div>
            <div className="text-2xl font-semibold font-num mt-1 text-red-700 dark:text-red-400">{summary.failing}</div>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Adapter</th>
              <th className="px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Last run</th>
              <th className="px-3 py-2 text-right font-medium">Last success</th>
              <th className="px-3 py-2 text-right font-medium font-num">Rows</th>
              <th className="px-3 py-2 text-right font-medium">Fails</th>
            </tr>
          </thead>
          <tbody>
            {data.sources.map((s) => (
              <tr
                key={s.source}
                className="border-t border-border hover:bg-accent/30 transition-colors"
              >
                <td className="px-3 py-2 font-mono text-xs">{s.source}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={s.status} />
                </td>
                <td className="px-3 py-2 text-right text-xs text-muted-foreground">
                  {formatTimeAgo(s.last_run_at)}
                </td>
                <td className="px-3 py-2 text-right text-xs text-muted-foreground">
                  {formatTimeAgo(s.last_success_at)}
                </td>
                <td className="px-3 py-2 text-right font-num tabular-nums">
                  {s.last_rows?.toLocaleString() ?? "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  {s.consecutive_failures > 0 ? (
                    <span className="text-red-600 dark:text-red-400 font-num">
                      {s.consecutive_failures}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">0</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.sources.some((s) => s.last_error) && (
        <details className="text-sm text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground">
            Show last errors ({data.sources.filter((s) => s.last_error).length})
          </summary>
          <div className="mt-2 space-y-2">
            {data.sources
              .filter((s) => s.last_error)
              .map((s) => (
                <div
                  key={s.source}
                  className="rounded-md border border-border bg-muted/30 p-3 text-xs"
                >
                  <div className="font-mono font-medium">{s.source}</div>
                  <div className="mt-1 font-mono text-red-700 dark:text-red-400 whitespace-pre-wrap">
                    {s.last_error}
                  </div>
                </div>
              ))}
          </div>
        </details>
      )}

      <p className="text-xs text-muted-foreground">
        Auto-refreshes every 60s. Per-adapter freshness is written by every
        ingest flow into the <code>source_health</code> table. Failing adapters
        appear in <code>docs/runbooks/</code> if the failure mode is recurring.
      </p>
    </div>
  );
}
