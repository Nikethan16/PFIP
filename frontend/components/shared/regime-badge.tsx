"use client";

import { cn } from "@/lib/utils";
import type { Regime } from "@/lib/contracts";

/**
 * Colored badge per regime.
 *
 * Colours roughly follow convention:
 *   bull_trend     → emerald
 *   accumulation   → teal
 *   bear_trend     → red
 *   distribution   → rose
 *   sideways       → slate
 *   high_volatility→ amber/orange
 */
const REGIME_STYLES: Record<Regime, string> = {
  bull_trend:
    "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  bear_trend:
    "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30",
  sideways:
    "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/30",
  high_volatility:
    "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/30",
  accumulation:
    "bg-teal-500/15 text-teal-700 dark:text-teal-300 border-teal-500/30",
  distribution:
    "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30",
};

const LABELS: Record<Regime, string> = {
  bull_trend: "Bull",
  bear_trend: "Bear",
  sideways: "Sideways",
  high_volatility: "High vol",
  accumulation: "Accum",
  distribution: "Distrib",
};

// Neutral, unlabelled state surfaced by the backend when a symbol has no
// regime row yet (`regime: "unknown"`). Rendered as a muted "No regime" pill.
const UNKNOWN_STYLE =
  "bg-muted text-muted-foreground border-border";
const UNKNOWN_LABEL = "No regime";

interface RegimeBadgeProps {
  regime: Regime | "unknown";
  className?: string;
  size?: "sm" | "md";
  showConfidence?: number;
}

export function RegimeBadge({
  regime,
  className,
  size = "sm",
  showConfidence,
}: RegimeBadgeProps) {
  const isUnknown = regime === "unknown";
  const style = isUnknown ? UNKNOWN_STYLE : REGIME_STYLES[regime];
  const label = isUnknown ? UNKNOWN_LABEL : LABELS[regime];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border font-medium uppercase tracking-wider",
        style,
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs",
        className,
      )}
      aria-label={`Regime: ${label}`}
    >
      <span>{isUnknown ? "—" : label}</span>
      {!isUnknown && showConfidence != null ? (
        <span className="font-normal opacity-75">
          {Math.round(showConfidence * 100)}%
        </span>
      ) : null}
    </span>
  );
}
