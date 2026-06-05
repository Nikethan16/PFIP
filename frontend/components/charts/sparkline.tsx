"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
  /**
   * Tone: "auto" infers from the first→last delta; otherwise force a colour.
   * Falls back to the foreground colour when there's no delta.
   */
  tone?: "auto" | "up" | "down" | "neutral";
  strokeWidth?: number;
  /** Optional accessible label. */
  ariaLabel?: string;
}

/**
 * Minimal inline sparkline rendered as pure SVG (no Recharts overhead).
 * Good for table cells, KPI strips, and watchlist tiles.
 *
 * Tracks the polyline, fills the area beneath with a faint gradient matching
 * the trend colour, and adds a tiny end-dot.
 */
export function Sparkline({
  values,
  width = 80,
  height = 24,
  className,
  tone = "auto",
  strokeWidth = 1.5,
  ariaLabel,
}: SparklineProps) {
  const gradId = React.useId();

  if (!values || values.length < 2) {
    return (
      <span
        className={cn(
          "inline-block text-[10px] text-muted-foreground",
          className,
        )}
        style={{ width, height }}
        aria-label={ariaLabel ?? "Not enough data"}
      >
        —
      </span>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = width / (values.length - 1);

  const points = values
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const last = values[values.length - 1] ?? 0;
  const first = values[0] ?? 0;
  const delta = last - first;

  const resolvedTone =
    tone === "auto"
      ? delta > 0
        ? "up"
        : delta < 0
          ? "down"
          : "neutral"
      : tone;

  const stroke =
    resolvedTone === "up"
      ? "rgb(16 185 129)"
      : resolvedTone === "down"
        ? "rgb(239 68 68)"
        : "hsl(var(--muted-foreground))";

  const endX = (values.length - 1) * stepX;
  const endY = height - ((last - min) / range) * height;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn("inline-block align-middle", className)}
      role="img"
      aria-label={ariaLabel ?? "Sparkline"}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.25" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={`0,${height} ${points} ${width},${height}`}
        fill={`url(#${gradId})`}
      />
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={endX} cy={endY} r={1.6} fill={stroke} />
    </svg>
  );
}
