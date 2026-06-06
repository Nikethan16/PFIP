"use client";

import * as React from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { OHLCV } from "@/lib/contracts";
import { formatIST, formatISTDate } from "@/lib/utils";

interface CandleChartProps {
  data: OHLCV[];
  height?: number;
}

/**
 * OHLCV chart, Sahara-styled: a flowing amber close-line over a soft
 * amber→transparent area fill, with the high-low range and volume kept as
 * faint secondary bars. Reads like the editorial price chart in the mockup
 * while the tooltip still surfaces the full OHLC + volume.
 */
export function CandleChart({ data, height = 280 }: CandleChartProps) {
  const shaped = React.useMemo(() => {
    return data.map((row) => ({
      ...row,
      range: [row.low, row.high] as [number, number],
      up: row.close >= row.open,
    }));
  }, [data]);

  if (!data.length) {
    return (
      <div
        className="flex w-full items-center justify-center border border-dashed text-sm text-muted-foreground"
        style={{ height }}
      >
        No candle data available yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart
        data={shaped}
        margin={{ top: 8, right: 36, left: 0, bottom: 0 }}
      >
        <defs>
          <linearGradient id="pfip-close-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.18} />
            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" opacity={0.12} vertical={false} />
        <XAxis
          dataKey="time"
          tickFormatter={(value: string) => formatISTDate(value)}
          stroke="currentColor"
          fontSize={11}
          minTickGap={24}
          tickLine={false}
          axisLine={false}
          className="font-mono text-muted-foreground"
        />
        <YAxis
          yAxisId="price"
          domain={["auto", "auto"]}
          stroke="currentColor"
          fontSize={11}
          width={52}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => Number(v).toFixed(0)}
          className="font-mono text-muted-foreground"
        />
        <YAxis
          yAxisId="vol"
          orientation="right"
          domain={[0, (d: number) => d * 4]}
          hide
        />
        <Tooltip
          cursor={{ stroke: "hsl(var(--foreground))", strokeOpacity: 0.25, strokeWidth: 1 }}
          labelFormatter={(v) => formatIST(String(v))}
          content={<OhlcTooltip />}
        />
        {/* Volume — faint amber columns on the hidden right axis. */}
        <Bar
          dataKey="volume"
          yAxisId="vol"
          fill="hsl(var(--primary))"
          fillOpacity={0.08}
          barSize={3}
          isAnimationActive={false}
        />
        {/* High-low shadow — thin translucent range marker. */}
        <Bar
          dataKey="range"
          yAxisId="price"
          fill="hsl(var(--primary))"
          fillOpacity={0.14}
          barSize={1.5}
          isAnimationActive={false}
        />
        {/* Soft area fill under the close. */}
        <Area
          type="monotone"
          dataKey="close"
          yAxisId="price"
          stroke="none"
          fill="url(#pfip-close-fill)"
          isAnimationActive={false}
        />
        {/* Close line — the hero amber stroke. */}
        <Line
          type="monotone"
          dataKey="close"
          yAxisId="price"
          stroke="hsl(var(--primary))"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

interface TooltipPayload {
  payload?: OHLCV & { up?: boolean };
}

function OhlcTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const up = row.close >= row.open;
  return (
    <div className="border bg-popover p-2 font-mono text-[11px] text-popover-foreground shadow-md">
      <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {formatIST(String(label))}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 tabular-nums">
        <span className="text-muted-foreground">O</span>
        <span>{row.open.toFixed(2)}</span>
        <span className="text-muted-foreground">H</span>
        <span>{row.high.toFixed(2)}</span>
        <span className="text-muted-foreground">L</span>
        <span>{row.low.toFixed(2)}</span>
        <span className="text-muted-foreground">C</span>
        <span className={up ? "text-emerald-500" : "text-red-500"}>
          {row.close.toFixed(2)}
        </span>
        <span className="text-muted-foreground">Vol</span>
        <span>{Math.round(row.volume).toLocaleString()}</span>
      </div>
    </div>
  );
}
