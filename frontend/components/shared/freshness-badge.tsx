"use client";

/**
 * Generic data-freshness badge — drop next to any KPI / card / chart whose
 * underlying data comes from a known ingest adapter. Reads the cached
 * `/api/v1/health/sources` query (poll handled centrally by
 * `useSourceHealth`, default 60s refetch), looks up the row for the
 * adapter name(s) provided, and renders a colored dot + tooltip with the
 * last-success age.
 *
 * Usage:
 *
 *   <FreshnessBadge sources={["coinbase_ohlcv", "fred_macro"]} />
 *
 * Behaviour:
 * - All sources healthy → small green dot, tooltip "Fresh — last updated …"
 * - Any stale → yellow dot, tooltip lists the stalest
 * - Any failing → red dot, tooltip lists the failing adapter + consecutive_failures
 * - None of the sources have ever run → gray dot, tooltip "No data yet"
 * - Query loading → invisible (keeps layout stable)
 *
 * Intentionally tiny; the Settings → Source health panel is the
 * full-fidelity view.
 */

import { useSourceHealth, type SourceHealth } from "@/lib/api";

type Props = {
  /** Adapter names to consult. Should match `source_health.source` values. */
  sources: string[];
  /** Optional override label rendered alongside the dot. */
  label?: string;
  className?: string;
};

type AggregateStatus = "healthy" | "stale" | "failing" | "never_run" | "loading";

function pickStatus(rows: SourceHealth[]): AggregateStatus {
  if (rows.length === 0) return "never_run";
  if (rows.some((r) => r.status === "failing")) return "failing";
  if (rows.some((r) => r.status === "stale")) return "stale";
  if (rows.every((r) => r.status === "never_run")) return "never_run";
  return "healthy";
}

function fmtAge(iso: string | null): string {
  if (!iso) return "never";
  const d = Date.now() - new Date(iso).getTime();
  if (d < 60_000) return `${Math.round(d / 1000)}s`;
  if (d < 3_600_000) return `${Math.round(d / 60_000)}m`;
  if (d < 86_400_000) return `${Math.round(d / 3_600_000)}h`;
  return `${Math.round(d / 86_400_000)}d`;
}

function dotClasses(status: AggregateStatus): string {
  switch (status) {
    case "healthy":
      return "bg-green-500";
    case "stale":
      return "bg-yellow-500";
    case "failing":
      return "bg-red-500 animate-pulse";
    case "never_run":
      return "bg-muted-foreground/50";
    case "loading":
      return "bg-transparent";
  }
}

export function FreshnessBadge({ sources, label, className = "" }: Props) {
  const q = useSourceHealth();
  if (q.isLoading || !q.data) {
    return (
      <span
        className={`inline-flex items-center gap-1 text-xs text-muted-foreground ${className}`}
        aria-hidden="true"
      >
        <span className={`h-1.5 w-1.5 rounded-full ${dotClasses("loading")}`} />
      </span>
    );
  }

  const wanted = new Set(sources);
  const matched = q.data.sources.filter((r) => wanted.has(r.source));
  const status = pickStatus(matched);

  // Build tooltip text — most informative status leads.
  let tooltip: string;
  if (matched.length === 0) {
    tooltip = `No source-health row yet for ${sources.join(", ")}`;
  } else if (status === "failing") {
    const worst = matched.find((r) => r.status === "failing")!;
    tooltip =
      `Failing: ${worst.source} ` +
      `(${worst.consecutive_failures}× consecutive). ` +
      `Last success ${fmtAge(worst.last_success_at)} ago.`;
  } else if (status === "stale") {
    const sorted = [...matched].sort((a, b) => {
      const ta = a.last_success_at ? new Date(a.last_success_at).getTime() : 0;
      const tb = b.last_success_at ? new Date(b.last_success_at).getTime() : 0;
      return ta - tb;
    });
    const stalest = sorted[0];
    tooltip = stalest
      ? `Stale: ${stalest.source} last updated ${fmtAge(stalest.last_success_at)} ago.`
      : `Stale data for ${sources.join(", ")}.`;
  } else if (status === "never_run") {
    tooltip = `Adapters not yet run: ${sources.join(", ")}.`;
  } else {
    const sorted = [...matched].sort((a, b) => {
      const ta = a.last_success_at ? new Date(a.last_success_at).getTime() : 0;
      const tb = b.last_success_at ? new Date(b.last_success_at).getTime() : 0;
      return tb - ta;
    });
    const newest = sorted[0];
    tooltip = newest
      ? `Fresh — ${newest.source} updated ${fmtAge(newest.last_success_at)} ago.`
      : `Fresh — ${sources.join(", ")}.`;
  }

  return (
    <span
      title={tooltip}
      aria-label={tooltip}
      className={`inline-flex items-center gap-1 text-xs text-muted-foreground cursor-help ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotClasses(status)}`} />
      {label && <span>{label}</span>}
    </span>
  );
}
