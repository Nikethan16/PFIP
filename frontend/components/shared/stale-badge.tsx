"use client";

import * as React from "react";
import { Clock } from "lucide-react";

import { cn } from "@/lib/utils";

interface StaleBadgeProps {
  /** ISO-8601 timestamp of when the data was last updated. */
  updatedAt?: string | Date | null;
  /** Threshold (minutes) above which the badge turns red. Default 60. */
  warnAfterMins?: number;
  className?: string;
  iconOnly?: boolean;
}

/**
 * Renders "Last updated X min ago" with a traffic-light colour:
 *   fresh        (< warn/3)  → muted
 *   getting old  (< warn)    → amber
 *   stale        (>= warn)   → red
 */
export function StaleBadge({
  updatedAt,
  warnAfterMins = 60,
  className,
  iconOnly,
}: StaleBadgeProps) {
  const [now, setNow] = React.useState(() => Date.now());

  React.useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  if (!updatedAt) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-[10px] text-muted-foreground",
          className,
        )}
      >
        <Clock className="h-3 w-3" />
        {iconOnly ? null : "No data yet"}
      </span>
    );
  }

  const ts = updatedAt instanceof Date ? updatedAt.getTime() : new Date(updatedAt).getTime();
  const mins = Math.max(0, Math.round((now - ts) / 60_000));
  const tone =
    mins >= warnAfterMins
      ? "text-red-600 dark:text-red-400"
      : mins >= warnAfterMins / 3
        ? "text-amber-600 dark:text-amber-400"
        : "text-muted-foreground";

  let label: string;
  if (mins < 1) label = "just now";
  else if (mins < 60) label = `${mins} min ago`;
  else if (mins < 60 * 24) label = `${Math.round(mins / 60)} h ago`;
  else label = `${Math.round(mins / (60 * 24))} d ago`;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[10px]",
        tone,
        className,
      )}
      title={`Updated ${label}`}
    >
      <Clock className="h-3 w-3" />
      {iconOnly ? null : <span>Last updated {label}</span>}
    </span>
  );
}
