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
  /** Optional trailing slot — e.g. sparkline or badge. */
  trailing?: React.ReactNode;
  /**
   * Freshness indicator dot rendered inline before the label.
   * Mirrors the Stitch dashboard pattern where every KPI carries a
   * green/amber/red dot tied to source health.
   */
  freshness?: "fresh" | "stale" | "failing";
}

/**
 * Dashboard hero KPI tile.
 *
 *   ┌──────────────────────┐
 *   │ LABEL          [icn] │
 *   │ 1,23,45,000          │
 *   │ ↑ 1.42%  +12k today  │
 *   └──────────────────────┘
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
  trailing,
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
      ? "text-emerald-600 dark:text-emerald-400"
      : resolvedTone === "down"
        ? "text-red-600 dark:text-red-400"
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
    <div className={cn("kpi-card p-4 transition-colors hover:bg-accent/30", className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 eyebrow">
          {freshnessClass ? (
            <span className={cn("freshness-dot !m-0", freshnessClass)} />
          ) : null}
          {label}
        </div>
        {icon ? <div className="text-muted-foreground">{icon}</div> : null}
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
              "mt-1.5 font-mono font-semibold tracking-tight tabular-nums",
              "text-2xl",
              // When the caller hasn't pinned a tone, prefer the institutional
              // teal accent on the headline number (Stitch convention).
              tone === undefined && deltaPct == null
                ? "text-primary"
                : "text-foreground",
            )}
          >
            {value}
          </div>
          <div className="mt-1 flex items-center justify-between gap-2">
            <div className={cn("flex items-center gap-1 text-xs", toneClass)}>
              {deltaPct != null ? (
                <>
                  <Arrow className="h-3 w-3" />
                  <span className="font-num font-medium">
                    {deltaPct > 0 ? "+" : ""}
                    {deltaPct.toFixed(2)}%
                  </span>
                </>
              ) : null}
              {hint ? (
                <span className="text-muted-foreground">{hint}</span>
              ) : null}
            </div>
            {trailing}
          </div>
        </>
      )}
    </div>
  );
}
