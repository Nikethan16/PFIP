"use client";

/**
 * Benchmark — am I actually beating the index?
 *
 * Compares the live portfolio's value path to a benchmark (NIFTY 50 / SENSEX /
 * S&P 500 / SPY) over 1M/3M/YTD/1Y/Max, showing portfolio return, benchmark
 * return, and the excess. Data: useBenchmark(symbol) → GET /portfolio/benchmark.
 */

import * as React from "react";
import { Trophy } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useBenchmark } from "@/lib/api";
import { cn } from "@/lib/utils";

const BENCHMARKS = ["NIFTY 50", "SENSEX", "S&P 500", "SPY"];
const WINDOW_ORDER = ["1M", "3M", "YTD", "1Y", "Max"];

function pct(v: number | null): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}

export default function BenchmarkPage() {
  const [symbol, setSymbol] = React.useState(BENCHMARKS[0]);
  const { data, isLoading, error } = useBenchmark(symbol);

  return (
    <div className="space-y-6">
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Performance // vs the index</div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Benchmark
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Your portfolio&apos;s time-weighted return against a market index,
            and the excess you earned (or gave up) over each window.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="font-label text-[11px] uppercase tracking-wider text-muted-foreground">
            Benchmark
          </span>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="border border-border bg-background px-3 py-2 font-mono text-sm"
          >
            {BENCHMARKS.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading ? (
        <Skeleton className="h-72 w-full" />
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load benchmark: {(error as Error).message}
        </div>
      ) : !data ? (
        <EmptyState icon={Trophy} title="No comparison" description="No data." />
      ) : (
        <section className="border border-border/60 bg-card">
          <div className="border-b border-border/40 p-5">
            <div className="eyebrow">{data.benchmark} ({data.benchmark_symbol_resolved})</div>
            <h3 className="mt-1 font-serif text-xl tracking-tight">
              Portfolio vs benchmark
            </h3>
          </div>
          {data.note ? (
            <p className="border-b border-border/40 bg-secondary/20 px-5 py-2 text-xs text-muted-foreground">
              {data.note}
            </p>
          ) : null}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/40 bg-secondary/30 text-left font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-5 py-2.5 font-medium">Window</th>
                  <th className="px-3 py-2.5 text-right font-medium">Portfolio</th>
                  <th className="px-3 py-2.5 text-right font-medium">Benchmark</th>
                  <th className="px-5 py-2.5 text-right font-medium">Excess</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {WINDOW_ORDER.filter((w) => data.windows[w]).map((w) => {
                  const row = data.windows[w];
                  const excess = row.excess_return;
                  return (
                    <tr key={w} className="hover-tile">
                      <td className="px-5 py-2.5 font-label text-xs uppercase tracking-wider">
                        {w}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                        {pct(row.portfolio_return)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">
                        {pct(row.benchmark_return)}
                      </td>
                      <td
                        className={cn(
                          "px-5 py-2.5 text-right font-mono font-semibold tabular-nums",
                          excess == null
                            ? "text-muted-foreground"
                            : excess >= 0
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-destructive",
                        )}
                      >
                        {pct(excess)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
