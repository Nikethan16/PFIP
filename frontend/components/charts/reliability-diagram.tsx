"use client";

import * as React from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import type { ReliabilityBin } from "@/lib/contracts";

interface ReliabilityDiagramProps {
  bins: ReliabilityBin[];
  height?: number;
}

/**
 * Reliability diagram for calibration. Bin centres vs empirical frequency,
 * overlaid against the 45° perfect-calibration reference.
 */
export function ReliabilityDiagram({
  bins,
  height = 280,
}: ReliabilityDiagramProps) {
  const data = React.useMemo(
    () =>
      bins.map((b) => ({
        x: b.predicted_mean,
        y: b.observed_freq,
        count: b.count,
      })),
    [bins],
  );

  const reference = [
    { x: 0, y: 0 },
    { x: 1, y: 1 },
  ];

  return (
    <div className="relative w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(var(--border))"
            opacity={0.4}
          />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, 1]}
            tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
            label={{ value: "Predicted", position: "insideBottom", offset: -2 }}
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0, 1]}
            tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
            label={{ value: "Observed", angle: -90, position: "insideLeft" }}
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
          />
          <ZAxis type="number" dataKey="count" range={[50, 400]} />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number) =>
              typeof value === "number" ? value.toFixed(3) : value
            }
          />
          <Scatter data={data} fill="hsl(var(--primary))" />
        </ScatterChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={reference}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          >
            <XAxis type="number" dataKey="x" domain={[0, 1]} hide />
            <YAxis type="number" dataKey="y" domain={[0, 1]} hide />
            <Line
              type="linear"
              dataKey="y"
              stroke="hsl(var(--primary))"
              strokeOpacity={0.5}
              strokeDasharray="4 4"
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
