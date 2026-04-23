"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { useCorrelationMatrix } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";

/**
 * Pairwise correlation heatmap. Cells coloured by sign + magnitude:
 *   +1 deep emerald, 0 neutral, -1 deep red.
 *
 * Mobile: wrapped in an `overflow-x-auto` scroller so tight viewports scroll
 * horizontally rather than squishing cells.
 */
export function CorrelationMatrix() {
  const { data, isLoading, error } = useCorrelationMatrix();

  if (isLoading) return <Skeleton className="h-56 w-full" />;
  if (error)
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-xs text-destructive">
        Correlations unavailable.
      </div>
    );
  if (!data || !data.symbols.length)
    return (
      <EmptyState
        title="No correlation data yet"
        description="Add at least 2 holdings to see pairwise correlations."
      />
    );

  const { symbols, matrix, window_days } = data;

  return (
    <div>
      <div className="mb-2 text-xs text-muted-foreground">
        Trailing {window_days}d · close-to-close returns
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-max border-collapse text-[11px]" role="table">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-card p-1" />
              {symbols.map((s) => (
                <th
                  key={s}
                  className="p-1 text-center font-medium text-muted-foreground"
                  scope="col"
                >
                  <span className="inline-block -rotate-45 px-1 text-[10px]">
                    {s}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {symbols.map((row, i) => (
              <tr key={row}>
                <th
                  className="sticky left-0 z-10 bg-card p-1 text-right text-[10px] font-medium text-muted-foreground"
                  scope="row"
                >
                  {row}
                </th>
                {symbols.map((col, j) => {
                  const v = matrix[i]?.[j] ?? 0;
                  return (
                    <td
                      key={col}
                      className={cn(
                        "pfip-heatmap-cell h-7 w-7 p-0 text-center align-middle text-[10px]",
                      )}
                      title={`${row} vs ${col}: ${v.toFixed(2)}`}
                    >
                      <div
                        className="mx-auto flex h-7 w-7 items-center justify-center rounded-sm"
                        style={{ backgroundColor: corrColor(v) }}
                      >
                        <span className={v > 0.5 || v < -0.5 ? "text-white" : "text-foreground"}>
                          {v.toFixed(2)}
                        </span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Legend />
    </div>
  );
}

function corrColor(v: number): string {
  // v in [-1, 1] → hsla; emerald (positive) / red (negative), muted at 0.
  const clamped = Math.max(-1, Math.min(1, v));
  if (clamped >= 0) {
    // 160deg = emerald-ish
    const light = 90 - 40 * clamped;
    return `hsl(160 70% ${light}%)`;
  }
  const light = 90 + 40 * clamped; // clamped is negative
  return `hsl(0 75% ${light}%)`;
}

function Legend() {
  return (
    <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
      <span>-1</span>
      <div
        className="h-2 flex-1 rounded"
        style={{
          background:
            "linear-gradient(to right, hsl(0 75% 50%), hsl(0 75% 90%), hsl(160 70% 90%), hsl(160 70% 50%))",
        }}
      />
      <span>+1</span>
    </div>
  );
}
