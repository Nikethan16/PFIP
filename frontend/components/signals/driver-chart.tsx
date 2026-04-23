"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Driver } from "@/lib/contracts";

interface DriverChartProps {
  drivers: Driver[];
  counterArguments?: Driver[];
  height?: number;
}

/**
 * SHAP-style horizontal bar chart. Positive contributions bar right (green),
 * negative bar left (red). `counterArguments` are appended with the sign
 * flipped so the user sees them on the "against" side.
 */
export function DriverChart({
  drivers,
  counterArguments = [],
  height = 180,
}: DriverChartProps) {
  const rows = React.useMemo(() => {
    const combined = [
      ...drivers.map((d) => ({ ...d })),
      ...counterArguments.map((d) => ({
        ...d,
        contribution: -Math.abs(d.contribution),
      })),
    ];
    return combined.sort(
      (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
    );
  }, [drivers, counterArguments]);

  if (!rows.length) {
    return (
      <div className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
        No drivers attached.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 4, right: 8, left: 8, bottom: 4 }}
      >
        <XAxis
          type="number"
          domain={[
            (dataMin: number) => Math.min(dataMin, -0.01),
            (dataMax: number) => Math.max(dataMax, 0.01),
          ]}
          tickFormatter={(v) => v.toFixed(2)}
          fontSize={10}
        />
        <YAxis
          type="category"
          dataKey="feature"
          width={120}
          fontSize={11}
          interval={0}
        />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 6,
            fontSize: 11,
          }}
          formatter={(v: number) => [v.toFixed(3), "SHAP"]}
        />
        <Bar dataKey="contribution" barSize={12}>
          {rows.map((r, i) => (
            <Cell
              key={i}
              fill={
                r.contribution >= 0 ? "rgb(16 185 129)" : "rgb(239 68 68)"
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
