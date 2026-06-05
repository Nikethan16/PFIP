"use client";

/**
 * Macro Shock Sensitivity card — Stitch design parity for the Portfolio page.
 *
 * Reads from `useVarPanel()` when the backend ships a `macro_shocks` array
 * (a `[{ scenario, delta_pct }]` payload from the stress-test scheduled
 * flow). Falls back to a deliberate "no shock data yet" empty state until
 * that endpoint is wired — we do NOT fabricate fake shock numbers.
 *
 * The shock list deliberately uses the surcharge / VAR convention:
 *   - Crude Oil +20% → expected portfolio delta
 *   - USD/INR +5% → expected portfolio delta
 *   - Equities -15% → expected portfolio delta
 *   - Crypto -25% → expected portfolio delta
 *   - Rates +200bps → expected portfolio delta
 *
 * Each row renders as a horizontal mini-bar that fills positive (green)
 * or negative (red) relative to a zero centerline.
 */

import { useVarPanel } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface ShockRow {
  scenario: string;
  delta_pct: number;
}

function isShockRow(row: unknown): row is ShockRow {
  if (typeof row !== "object" || row === null) return false;
  const r = row as Record<string, unknown>;
  return typeof r.scenario === "string" && typeof r.delta_pct === "number";
}

export function MacroShockCard() {
  const { data, isLoading } = useVarPanel();

  // Tolerantly look for a `macro_shocks` field; the backend will add this
  // when the stress-test scheduled flow lands. Until then we read empty.
  const raw = (data as Record<string, unknown> | undefined)?.macro_shocks;
  const shocks: ShockRow[] = Array.isArray(raw)
    ? raw.filter(isShockRow)
    : [];

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Macro shock sensitivity</p>
          <p className="text-xs text-muted-foreground">
            Expected portfolio impact under stress scenarios.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2.5">
        {isLoading ? (
          <>
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-full" />
          </>
        ) : shocks.length === 0 ? (
          <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
            No shock data yet. Stress-test flow runs monthly; first results
            appear after the next scheduled run. See
            <code className="ml-1 rounded bg-muted/40 px-1 text-[10px]">
              pfip.risk.stress
            </code>
            .
          </p>
        ) : (
          shocks.map((s) => <ShockBar key={s.scenario} {...s} />)
        )}
      </div>
    </div>
  );
}

function ShockBar({ scenario, delta_pct }: ShockRow) {
  const positive = delta_pct >= 0;
  const magnitude = Math.min(Math.abs(delta_pct), 50); // cap visual at 50%
  const width = `${(magnitude / 50) * 50}%`;
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 truncate text-[11px] text-muted-foreground">
        {scenario}
      </span>
      <div className="relative flex-1">
        <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted/40">
          <div
            className={cn(
              "absolute top-0 h-full rounded-full",
              positive ? "bg-emerald-500/80" : "bg-red-500/80",
            )}
            style={{
              [positive ? "left" : "right"]: "50%",
              width,
            }}
          />
          <div className="absolute left-1/2 top-1/2 h-2 w-px -translate-x-1/2 -translate-y-1/2 bg-border" />
        </div>
      </div>
      <span
        className={cn(
          "w-14 text-right font-mono text-[11px] tabular-nums",
          positive
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-red-600 dark:text-red-400",
        )}
      >
        {positive ? "+" : ""}
        {delta_pct.toFixed(1)}%
      </span>
    </div>
  );
}
