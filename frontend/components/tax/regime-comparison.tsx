"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatINR } from "@/lib/utils";

interface RegimeComparisonProps {
  oldRegimeInr: number;
  newRegimeInr: number;
}

/**
 * Old vs New tax regime head-to-head. Simple grouped bar + explicit savings
 * figure underneath so the user doesn't have to eyeball it.
 */
export function RegimeComparison({
  oldRegimeInr,
  newRegimeInr,
}: RegimeComparisonProps) {
  const data = [
    {
      name: "Total tax",
      Old: oldRegimeInr,
      New: newRegimeInr,
    },
  ];
  const diff = oldRegimeInr - newRegimeInr;
  const winner = diff > 0 ? "New" : diff < 0 ? "Old" : "Tied";

  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
          <XAxis
            type="number"
            tickFormatter={(v) => formatINR(v, 0)}
            fontSize={11}
          />
          <YAxis type="category" dataKey="name" hide />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number) => formatINR(value)}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="Old" fill="rgb(99 102 241)" />
          <Bar dataKey="New" fill="rgb(16 185 129)" />
        </BarChart>
      </ResponsiveContainer>
      <div className="rounded-md border bg-muted/30 p-2 text-xs">
        Recommended regime: <span className="font-semibold">{winner}</span>
        {diff !== 0 ? (
          <>
            {" "}
            · saves{" "}
            <span className="font-semibold">{formatINR(Math.abs(diff))}</span>
          </>
        ) : null}
      </div>
    </div>
  );
}
