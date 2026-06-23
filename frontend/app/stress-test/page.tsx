"use client";

/**
 * Stress Test — what a crisis would do to today's book.
 *
 * Applies named historical shock scenarios (2008 GFC, 2020 COVID, +200bps rate
 * shock, INR depreciation) per asset class to the current marked portfolio and
 * shows the projected loss, worst first. Data: useStressTest() →
 * GET /portfolio/stress-test. Scenario overlay, not a forecast.
 */

import { AlertTriangle, ShieldAlert } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { Kpi } from "@/components/shared/kpi";
import { EmptyState } from "@/components/shared/empty-state";
import { useStressTest } from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";

export default function StressTestPage() {
  const { data, isLoading, error } = useStressTest();
  const worst = data?.scenarios?.[0];

  return (
    <div className="space-y-6">
      <div className="page-header">
        <div className="eyebrow">Risk // scenario overlay</div>
        <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
          Stress Test
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          How today&apos;s allocation would fare under past crises. These are
          scenario shocks applied to your current book — not predictions.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Kpi
          label="Current value"
          value={data ? formatINR(data.current_value_inr) : "—"}
          hint="marked to market"
          loading={isLoading}
        />
        <Kpi
          label="Worst scenario"
          value={worst ? `${(worst.impact_pct * 100).toFixed(1)}%` : "—"}
          valueClassName="text-destructive"
          hint={worst?.label}
          icon={<ShieldAlert className="h-3.5 w-3.5" />}
          loading={isLoading}
          accent
        />
        <Kpi
          label="Worst-case loss"
          value={worst ? formatINR(worst.change_inr) : "—"}
          hint="peak-to-trough"
          icon={<AlertTriangle className="h-3.5 w-3.5" />}
          loading={isLoading}
        />
      </div>

      {isLoading ? (
        <Skeleton className="h-72 w-full" />
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t run stress test: {(error as Error).message}
        </div>
      ) : !data || data.scenarios.length === 0 || data.current_value_inr === 0 ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={ShieldAlert}
            title="Nothing to stress yet"
            description="Add holdings and the stress scenarios will show how a 2008- or COVID-style shock would hit your current allocation."
          />
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {data.scenarios.map((s) => (
            <section key={s.scenario} className="border border-border/60 bg-card p-5">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg tracking-tight">{s.label}</h3>
                <span
                  className={cn(
                    "font-mono text-lg font-semibold tabular-nums",
                    s.impact_pct < 0 ? "text-destructive" : "text-emerald-600 dark:text-emerald-400",
                  )}
                >
                  {(s.impact_pct * 100).toFixed(1)}%
                </span>
              </div>
              <p className="mt-1 font-mono text-sm tabular-nums text-muted-foreground">
                {formatINR(s.change_inr)} → {formatINR(s.shocked_value_inr)}
              </p>
              {Object.keys(s.category_pnl_inr).length ? (
                <div className="mt-3 space-y-1">
                  {Object.entries(s.category_pnl_inr)
                    .sort((a, b) => a[1] - b[1])
                    .map(([cat, pnl]) => (
                      <div
                        key={cat}
                        className="flex items-baseline justify-between gap-2 text-xs"
                      >
                        <span className="font-label uppercase tracking-wider text-muted-foreground">
                          {cat}
                        </span>
                        <span
                          className={cn(
                            "font-mono tabular-nums",
                            pnl < 0 ? "text-destructive" : "text-emerald-600 dark:text-emerald-400",
                          )}
                        >
                          {formatINR(pnl)}
                        </span>
                      </div>
                    ))}
                </div>
              ) : null}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
