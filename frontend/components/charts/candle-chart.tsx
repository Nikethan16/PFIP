"use client";

import * as React from "react";
import {
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
 * OHLCV composed chart:
 *   - high-low range as a thin translucent bar (candle-shadow proxy)
 *   - close as a bold line overlay
 *   - volume as a secondary (axis right) faint bar
 *
 * Tooltip shows full OHLC + volume.
 */
export function CandleChart({ data, height = 280 }: CandleChartProps) {
  const shaped = React.useMemo(() => {
    return data.map((row) => ({
      ...row,
      range: [row.low, row.high] as [number, number],
      body: [Math.min(row.open, row.close), Math.max(row.open, row.close)] as [
        number,
        number,
      ],
      up: row.close >= row.open,
    }));
  }, [data]);

  if (!data.length) {
    return (
      <div
        className="flex w-full items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground"
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
        <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
        <XAxis
          dataKey="time"
          tickFormatter={(value: string) => formatISTDate(value)}
          stroke="currentColor"
          fontSize={11}
          minTickGap={24}
        />
        <YAxis
          yAxisId="price"
          domain={["auto", "auto"]}
          stroke="currentColor"
          fontSize={11}
          width={52}
          tickFormatter={(v) => Number(v).toFixed(0)}
        />
        <YAxis
          yAxisId="vol"
          orientation="right"
          domain={[0, (d: number) => d * 4]}
          hide
        />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 6,
            fontSize: 12,
          }}
          labelFormatter={(v) => formatIST(String(v))}
          content={<OhlcTooltip />}
        />
        {/* Volume */}
        <Bar
          dataKey="volume"
          yAxisId="vol"
          fill="hsl(var(--primary))"
          fillOpacity={0.12}
          barSize={3}
          isAnimationActive={false}
        />
        {/* High-low shadow */}
        <Bar
          dataKey="range"
          yAxisId="price"
          fill="hsl(var(--primary))"
          fillOpacity={0.2}
          barSize={1.5}
          isAnimationActive={false}
        />
        {/* Candle body (open-close range) */}
        <Bar
          dataKey="body"
          yAxisId="price"
          fill="hsl(var(--primary))"
          fillOpacity={0.6}
          barSize={5}
          isAnimationActive={false}
        />
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
    <div className="rounded-md border bg-popover p-2 text-[11px] text-popover-foreground shadow-md">
      <div className="mb-1 text-[10px] font-medium text-muted-foreground">
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
