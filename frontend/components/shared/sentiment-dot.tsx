"use client";

import { cn } from "@/lib/utils";

interface SentimentDotProps {
  /** Sentiment in [-1, 1]. */
  value: number | null | undefined;
  className?: string;
  size?: "xs" | "sm" | "md";
  showLabel?: boolean;
}

/**
 * Small dot representing news / signal sentiment.
 *   < -0.2 → red
 *   -0.2..0.2 → muted
 *   > 0.2 → emerald
 */
export function SentimentDot({
  value,
  className,
  size = "sm",
  showLabel,
}: SentimentDotProps) {
  if (value == null || Number.isNaN(value)) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-[10px] text-muted-foreground",
          className,
        )}
        title="No sentiment score"
      >
        <span
          className={cn(
            "block rounded-full bg-muted-foreground/40",
            size === "xs" ? "h-1.5 w-1.5" : size === "md" ? "h-2.5 w-2.5" : "h-2 w-2",
          )}
        />
        {showLabel ? "n/a" : null}
      </span>
    );
  }
  const tone =
    value > 0.2 ? "emerald" : value < -0.2 ? "red" : "amber";
  const label = value > 0.2 ? "Positive" : value < -0.2 ? "Negative" : "Neutral";
  const dot =
    tone === "emerald"
      ? "bg-emerald-500"
      : tone === "red"
        ? "bg-red-500"
        : "bg-amber-500";
  const text =
    tone === "emerald"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "red"
        ? "text-red-600 dark:text-red-400"
        : "text-amber-600 dark:text-amber-400";
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-[10px]", text, className)}
      title={`${label} (${value.toFixed(2)})`}
    >
      <span
        className={cn(
          "block rounded-full",
          dot,
          size === "xs" ? "h-1.5 w-1.5" : size === "md" ? "h-2.5 w-2.5" : "h-2 w-2",
        )}
      />
      {showLabel ? <span>{label}</span> : null}
    </span>
  );
}
