"use client";

import * as React from "react";
import { Info } from "lucide-react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useVarPanel } from "@/lib/api";
import { formatINR, formatPct, formatISTDate } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";

/**
 * Panel bundling risk metrics: historical VaR, Herfindahl concentration,
 * daily-new-positions remaining counter and a 90-day drawdown sparkline.
 */
export function VarPanel() {
  const { data, isLoading, error } = useVarPanel();

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (error)
    return (
      <Card>
        <CardContent className="p-6 text-xs text-destructive">
          VaR panel unavailable.
        </CardContent>
      </Card>
    );
  if (!data)
    return (
      <Card>
        <CardContent>
          <EmptyState
            title="No risk metrics yet"
            description="Record at least 30 days of portfolio history."
          />
        </CardContent>
      </Card>
    );

  const hhi = data.concentration_hhi;
  const hhiLabel =
    hhi < 0.15 ? "Diversified" : hhi < 0.25 ? "Moderate" : "Concentrated";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Risk</CardTitle>
        <CardDescription>
          Historical VaR · concentration · drawdown trajectory
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric
            label="VaR 95%"
            value={formatINR(-Math.abs(data.var_95_inr))}
            sub={formatPct(-Math.abs(data.var_95_pct))}
            tone="amber"
          />
          <Metric
            label="VaR 99%"
            value={formatINR(-Math.abs(data.var_99_inr))}
            sub={formatPct(-Math.abs(data.var_99_pct))}
            tone="red"
          />
          <Metric
            label={
              <span className="inline-flex items-center gap-1">
                Concentration
                <span
                  title="Herfindahl-Hirschman Index: sum of squared weights. 0 = perfectly diversified, 1 = single holding. PFIP flags ≥ 0.25 as concentrated."
                >
                  <Info className="h-3 w-3 text-muted-foreground" />
                </span>
              </span>
            }
            value={hhi.toFixed(3)}
            sub={hhiLabel}
            tone={hhi >= 0.25 ? "red" : hhi >= 0.15 ? "amber" : "emerald"}
          />
          <Metric
            label="Sharpe 30d"
            value={data.sharpe_30d.toFixed(2)}
            sub={data.sharpe_30d >= 1 ? "Healthy" : "Watch"}
            tone={data.sharpe_30d >= 1 ? "emerald" : "amber"}
          />
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <span className="text-muted-foreground">
              Daily new-positions remaining
            </span>
            <span className="font-medium tabular-nums">
              {data.daily_new_positions_remaining}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
            <div
              className="h-full bg-primary transition-all"
              style={{
                width: `${Math.min(100, (data.daily_new_positions_remaining / 5) * 100)}%`,
              }}
              aria-label="Daily new positions remaining"
            />
          </div>
        </div>

        <div>
          <div className="mb-1 text-xs text-muted-foreground">
            Drawdown · trailing 90d
          </div>
          {data.drawdown_series.length ? (
            <ResponsiveContainer width="100%" height={96}>
              <AreaChart data={data.drawdown_series}>
                <defs>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="0%"
                      stopColor="rgb(239 68 68)"
                      stopOpacity={0.4}
                    />
                    <stop
                      offset="100%"
                      stopColor="rgb(239 68 68)"
                      stopOpacity={0.02}
                    />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  hide
                  tickFormatter={(v) => formatISTDate(v)}
                />
                <YAxis domain={["auto", 0]} hide />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                  labelFormatter={(v) => formatISTDate(String(v))}
                  formatter={(value: number) => [formatPct(value), "DD"]}
                />
                <Area
                  type="monotone"
                  dataKey="drawdown_pct"
                  stroke="rgb(239 68 68)"
                  fill="url(#ddGrad)"
                  strokeWidth={1.5}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-24 rounded-md border border-dashed p-3 text-center text-[11px] text-muted-foreground">
              Awaiting history.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  sub,
  tone = "muted",
}: {
  label: React.ReactNode;
  value: string;
  sub?: string;
  tone?: "emerald" | "amber" | "red" | "muted";
}) {
  const toneClass =
    tone === "emerald"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "amber"
        ? "text-amber-600 dark:text-amber-400"
        : tone === "red"
          ? "text-red-600 dark:text-red-400"
          : "text-foreground";
  return (
    <div className="rounded-md border p-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm font-semibold tabular-nums ${toneClass}`}>
        {value}
      </div>
      {sub ? (
        <div className="text-[10px] text-muted-foreground">{sub}</div>
      ) : null}
    </div>
  );
}
