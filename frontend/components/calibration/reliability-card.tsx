"use client";

import * as React from "react";
import {
  Line,
  LineChart,
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
import { Badge } from "@/components/ui/badge";
import { ReliabilityDiagram } from "@/components/charts/reliability-diagram";
import type { CalibrationReport } from "@/lib/contracts";
import type { CalibrationHistory } from "@/lib/api";
import { formatIST } from "@/lib/utils";

interface ReliabilityCardProps {
  report: CalibrationReport;
  history?: CalibrationHistory;
  /** Sharpness proxy: mean |predicted - 0.5| across bins. */
  sharpness?: number;
}

function scoreBadge(
  label: string,
  value: number,
  thresholds: [number, number],
) {
  const [good, ok] = thresholds;
  const variant =
    value <= good ? "success" : value <= ok ? "warning" : "destructive";
  return (
    <Badge variant={variant} className="text-[10px]">
      {label} {value.toFixed(3)}
    </Badge>
  );
}

/**
 * Per-model reliability summary card: Brier / ECE / sharpness + the reliability
 * diagram + a 6-month ECE trend sparkline. Flags a red "SUSPENDED" badge when
 * ECE > 0.15 for 2 consecutive months (determined server-side via
 * `history.suspended`).
 */
export function ReliabilityCard({
  report,
  history,
  sharpness,
}: ReliabilityCardProps) {
  // Prefer the backend-computed sharpness; fall back to the prop, then to a
  // local mean |predicted - 0.5| weighted by bin count.
  const computedSharpness = React.useMemo(() => {
    if (sharpness != null) return sharpness;
    if (report.sharpness != null) return report.sharpness;
    const total = report.reliability.reduce((a, b) => a + b.count, 0);
    if (!total) return 0;
    const sum = report.reliability.reduce(
      (a, b) => a + Math.abs(b.predicted_mean - 0.5) * b.count,
      0,
    );
    return sum / total;
  }, [report.reliability, report.sharpness, sharpness]);

  const suspended = history?.suspended ?? report.ece > 0.15;

  return (
    <Card className={suspended ? "border-destructive/40" : undefined}>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              {report.model_name}
              {suspended ? (
                <Badge variant="destructive" className="text-[10px]">
                  SUSPENDED
                </Badge>
              ) : null}
            </CardTitle>
            <CardDescription>
              v{report.model_version} · {report.n_samples.toLocaleString()}{" "}
              samples
              {report.created_at
                ? ` · ${formatIST(report.created_at, "dd MMM HH:mm")}`
                : ""}
            </CardDescription>
          </div>
          <div className="flex flex-col gap-1">
            {scoreBadge("Brier", report.brier, [0.15, 0.25])}
            {scoreBadge("ECE", report.ece, [0.05, 0.1])}
            {scoreBadge("Sharp", computedSharpness, [0.2, 0.35])}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ReliabilityDiagram bins={report.reliability} height={240} />

        {history?.points.length ? (
          <div>
            <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
              <span>ECE · last {history.points.length} points</span>
              <span>red line = 0.15 limit</span>
            </div>
            <ResponsiveContainer width="100%" height={64}>
              <LineChart data={history.points}>
                <XAxis dataKey="evaluated_at" hide />
                <YAxis domain={[0, "auto"]} hide />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                  labelFormatter={(v) => formatIST(String(v), "dd MMM")}
                  formatter={(v: number) => v.toFixed(3)}
                />
                <Line
                  type="monotone"
                  dataKey="ece"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey={() => 0.15}
                  stroke="rgb(239 68 68)"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  dot={false}
                  isAnimationActive={false}
                  legendType="none"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
