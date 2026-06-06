"use client";

import * as React from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface KpiProps {
  label: string;
  value: React.ReactNode;
  /** Secondary line — typically the delta or context. */
  hint?: React.ReactNode;
  /** Numeric delta in percent. Drives tone + arrow. */
  deltaPct?: number | null;
  /** Override tone explicitly. */
  tone?: "up" | "down" | "neutral";
  icon?: React.ReactNode;
  loading?: boolean;
  className?: string;
  /** Extra classes on the big value (e.g. to tint a P&L figure). */
  valueClassName?: string;
  /** Optional trailing slot — e.g. sparkline or badge. */
  trailing?: React.ReactNode;
  /**
   * Draws a flush amber left-stripe (Sahara "Risk Status" treatment) to single
   * out the most important tile in the strip.
   */
  accent?: boolean;
  /**
   * Freshness indicator dot rendered inline before the label.
   * Mirrors the Stitch dashboard pattern where every KPI carries a
   * green/amber/red dot tied to source health.
   */
  freshness?: "fresh" | "stale" | "failing";
}

/**
 * Dashboard hero KPI tile — Sahara institutional-terminal styling.
 *
 *   ┌──────────────────────┐
 *   │ NET WORTH       [icn] │   ← Archivo Narrow uppercase eyebrow
 *   │ ₹1,23,45,000          │   ← big JetBrains Mono number
 *   │ ↑ 1.42%  vs cost basis│
 *   └──────────────────────┘
 *
 * Thin warm border, square corners, amber accent number when neutral.
 */
export function Kpi({
  label,
  value,
  hint,
  deltaPct,
  tone,
  icon,
  loading,
  className,
  valueClassName,
  trailing,
  accent,
  freshness,
}: KpiProps) {
  const resolvedTone =
    tone ??
    (deltaPct == null
      ? "neutral"
      : deltaPct > 0
        ? "up"
        : deltaPct < 0
          ? "down"
          : "neutral");

  const toneClass =
    resolvedTone === "up"
      ? "text-emerald-700 dark:text-emerald-400"
      : resolvedTone === "down"
        ? "text-red-700 dark:text-red-400"
        : "text-muted-foreground";

  const Arrow =
    resolvedTone === "up"
      ? ArrowUpRight
      : resolvedTone === "down"
        ? ArrowDownRight
        : Minus;

  // Freshness dot color mapping (Stitch convention).
  const freshnessClass =
    freshness === "fresh"
      ? "bg-emerald-500"
      : freshness === "stale"
        ? "bg-amber-500"
        : freshness === "failing"
          ? "bg-red-500"
          : null;

  return (
    <div
      className={cn(
        "flex flex-col gap-1 border border-border/70 bg-card p-5 transition-colors hover:border-foreground/20",
        accent && "border-l-2 border-l-primary",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="eyebrow flex items-center gap-1.5">
          {freshnessClass ? (
            <span className={cn("freshness-dot !m-0", freshnessClass)} />
          ) : null}
          {label}
        </div>
        {icon ? <div className="text-muted-foreground/70">{icon}</div> : null}
      </div>
      {loading ? (
        <div className="mt-2 space-y-1.5">
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-3 w-16" />
        </div>
      ) : (
        <>
          <div
            className={cn(
              "mt-1 font-mono text-2xl font-semibold tracking-tight tabular-nums",
              // When the caller hasn't pinned a tone, prefer the institutional
              // amber accent on the headline number (Sahara convention).
              tone === undefined && deltaPct == null
                ? "text-foreground"
                : "text-foreground",
              valueClassName,
            )}
          >
            {value}
          </div>
          <div className="mt-0.5 flex items-center justify-between gap-2">
            <div className={cn("flex items-center gap-1 text-xs", toneClass)}>
              {deltaPct != null ? (
                <>
                  <Arrow className="h-3 w-3" />
                  <span className="font-mono font-medium tabular-nums">
                    {deltaPct > 0 ? "+" : ""}
                    {deltaPct.toFixed(2)}%
                  </span>
                </>
              ) : null}
              {hint ? (
                <span className="font-label uppercase tracking-wide text-muted-foreground/80">
                  {hint}
                </span>
              ) : null}
            </div>
            {trailing}
          </div>
        </>
      )}
    </div>
  );
}
