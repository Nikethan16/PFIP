"use client";

/**
 * Volatility (F2) — the realized-vol cone + forward forecast for an asset.
 *
 * The direction signals have no edge (all HOLD); volatility has real structure,
 * so this surfaces where current realized vol sits vs its own history across
 * horizons, plus the best-available forward estimate. Informational, not advice.
 */

import * as React from "react";
import { Activity, Search } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useVol, type ConeBucket } from "@/lib/api";
import { cn } from "@/lib/utils";

const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);

function toneForPercentile(p: number | null): string {
  if (p === null) return "text-muted-foreground";
  if (p >= 80) return "text-red-700 dark:text-red-400"; // vol historically high
  if (p <= 20) return "text-emerald-700 dark:text-emerald-400"; // historically calm
  return "text-amber-700 dark:text-amber-400";
}

export default function VolPage() {
  const [input, setInput] = React.useState("BTC-USD");
  const [symbol, setSymbol] = React.useState("BTC-USD");
  const { data, isLoading, error } = useVol(symbol);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Volatility"
        description="Realized-volatility cone — where current vol sits against its own history, per horizon — plus a forward estimate. The structure the direction model lacks."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim()) setSymbol(input.trim().toUpperCase());
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <div className="relative max-w-xs flex-1">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Symbol e.g. BTC-USD, AAPL, RELIANCE.NS"
            className="pl-7"
          />
        </div>
        <Button type="submit" size="sm">
          Analyze
        </Button>
      </form>

      {error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(error as Error).message}
        </div>
      ) : isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : !data || !data.cone.some((c) => c.current !== null) ? (
        <EmptyState
          icon={Activity}
          title={`Not enough price history for ${symbol}`}
          description="The vol cone needs a few months of daily closes. Try a tracked symbol."
        />
      ) : (
        <div className="space-y-5">
          {data.forecast ? (
            <div className="flex flex-wrap items-baseline gap-3 border border-border/60 bg-card p-4">
              <span className="eyebrow">Forward vol · {data.forecast.horizon_days}d</span>
              <span className="font-mono text-2xl tabular-nums">
                {(data.forecast.annual_vol * 100).toFixed(1)}%
              </span>
              <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                annualized · {data.forecast.source}
              </span>
            </div>
          ) : null}

          <div className="overflow-x-auto border border-border/60">
            <table className="w-full text-sm">
              <thead className="bg-secondary/40">
                <tr className="text-left">
                  {["Horizon", "Current", "Percentile", "P10", "Median", "P90", "Min", "Max"].map(
                    (h) => (
                      <th
                        key={h}
                        className={cn(
                          "px-3 py-2 font-label text-[10px] uppercase tracking-wider",
                          h !== "Horizon" && "text-right",
                        )}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.cone.map((b: ConeBucket) => (
                  <tr key={b.window_days} className="border-t border-border/40">
                    <td className="px-3 py-2 font-medium">{b.window_days}d</td>
                    <td className={cn("px-3 py-2 text-right font-mono tabular-nums", toneForPercentile(b.percentile))}>
                      {pct(b.current)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
                      {b.percentile === null ? "—" : `${b.percentile.toFixed(0)}th`}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">{pct(b.p10)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">{pct(b.p50)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">{pct(b.p90)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">{pct(b.min)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">{pct(b.max)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-muted-foreground">
            A high percentile means vol is historically elevated for that horizon (moves are large);
            a low percentile means unusually calm. {data.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}
