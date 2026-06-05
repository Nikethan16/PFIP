"use client";

import * as React from "react";
import { Activity } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatIST } from "@/lib/utils";
import type { Marking } from "@/lib/api";

interface MarkingBadgeProps {
  marking?: Marking;
  className?: string;
}

/** Human label for each abstention reason from `/portfolio/marking`. */
const REASON_LABELS: Record<string, string> = {
  no_price: "no recent price",
  unknown_currency: "currency unknown",
  no_fx_rate: "no FX rate",
};

/**
 * Unobtrusive mark-to-market coverage badge for the portfolio header.
 *
 * Shows "Live-priced: marked/total · as of <IST time>" and, on hover, lists the
 * unmarked symbols with the reason each fell back to cost basis. Degrades
 * gracefully: renders nothing while loading and "No holdings to price" when the
 * portfolio is empty.
 */
export function MarkingBadge({ marking, className }: MarkingBadgeProps) {
  if (!marking) return null;

  const { marked, total } = marking.coverage;

  if (total === 0) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-[10px] text-muted-foreground",
          className,
        )}
      >
        <Activity className="h-3 w-3" />
        No holdings to price
      </span>
    );
  }

  // Amber when some holdings fell back to cost basis; muted when fully live.
  const tone =
    marked < total
      ? "text-amber-600 dark:text-amber-400"
      : "text-muted-foreground";

  const asOf = marking.as_of ? formatIST(marking.as_of) : null;

  const unmarkedLines = marking.unmarked.map((u) => {
    const reason = REASON_LABELS[u.reason] ?? u.reason;
    return `${u.symbol} — ${reason}`;
  });

  const title = [
    asOf ? `Marked to market as of ${asOf}` : "Mark-to-market coverage",
    ...(unmarkedLines.length
      ? ["", "On cost basis:", ...unmarkedLines]
      : ["", "All holdings live-priced."]),
  ].join("\n");

  return (
    <span
      className={cn("inline-flex items-center gap-1 text-[10px]", tone, className)}
      title={title}
    >
      <Activity className="h-3 w-3" />
      <span>
        Live-priced: {marked}/{total}
        {asOf ? ` · as of ${asOf}` : null}
      </span>
    </span>
  );
}
