"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { formatINR } from "@/lib/utils";

interface SurchargeGaugeProps {
  incomeInr: number;
  thresholds: Array<{ threshold_inr: number; rate_pct: number }>;
}

/**
 * Visualises where the user sits relative to income thresholds that trigger
 * India surcharge steps (10% / 15% / 25% / 37%). A simple horizontal bar with
 * markers + labels; hoverable tooltips explain each step.
 */
export function SurchargeGauge({ incomeInr, thresholds }: SurchargeGaugeProps) {
  const sorted = [...thresholds].sort(
    (a, b) => a.threshold_inr - b.threshold_inr,
  );
  const max = Math.max(
    sorted[sorted.length - 1]?.threshold_inr ?? 50_000_000,
    incomeInr * 1.1,
  );
  const pct = (incomeInr / max) * 100;

  const currentStep = sorted
    .filter((t) => incomeInr >= t.threshold_inr)
    .pop();

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <div className="text-xs text-muted-foreground">Current income</div>
        <div className="text-sm font-semibold tabular-nums">
          {formatINR(incomeInr)}
        </div>
      </div>

      <div className="relative h-8 w-full rounded-md border bg-muted/40">
        <div
          className={cn(
            "absolute inset-y-0 left-0 rounded-md bg-gradient-to-r from-emerald-400 via-amber-400 to-red-500 transition-all",
          )}
          style={{ width: `${Math.min(100, pct)}%` }}
          aria-label={`Income at ${pct.toFixed(0)}% of highest surcharge step`}
        />
        {sorted.map((t) => {
          const left = (t.threshold_inr / max) * 100;
          return (
            <div
              key={t.threshold_inr}
              className="absolute top-0 flex h-full items-center"
              style={{ left: `${left}%` }}
              title={`${formatINR(t.threshold_inr)} → +${t.rate_pct}% surcharge`}
            >
              <div className="h-full w-[1px] bg-foreground/40" />
              <div className="ml-1 whitespace-nowrap rounded bg-background/90 px-1 py-0.5 text-[10px] font-medium shadow-sm">
                +{t.rate_pct}%
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap justify-between gap-2 text-[10px] text-muted-foreground">
        {sorted.map((t) => (
          <div key={t.threshold_inr} className="tabular-nums">
            {formatINR(t.threshold_inr)}
          </div>
        ))}
      </div>

      <div className="mt-2 text-xs">
        {currentStep ? (
          <span>
            Current surcharge:{" "}
            <span className="font-semibold">+{currentStep.rate_pct}%</span>
          </span>
        ) : (
          <span className="text-muted-foreground">
            Below the lowest surcharge threshold.
          </span>
        )}
      </div>
    </div>
  );
}
