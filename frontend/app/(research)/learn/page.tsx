"use client";

/**
 * Learn (D9) — teach an asset from scratch.
 *
 * Pick a symbol (e.g. BTC-USD) and see its price chart with the biggest swings
 * marked and explained by a real news catalyst where one exists, a beginner
 * primer, and general educational strategies. Explicitly educational — no
 * buy/sell affordances, no predictions.
 */

import * as React from "react";
import Link from "next/link";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ExternalLink, GraduationCap, Search, TrendingDown, TrendingUp } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/shared/markdown";
import { EmptyState } from "@/components/shared/empty-state";
import { useLearn, type LearnMove } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function LearnPage() {
  const [input, setInput] = React.useState("BTC-USD");
  const [symbol, setSymbol] = React.useState("BTC-USD");
  const { data, isLoading, error } = useLearn(symbol);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Learn"
        description="Understand an asset from scratch — its price story, why it moved, and how people approach it. Educational, not advice."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim()) setSymbol(input.trim().toUpperCase());
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <div className="relative max-w-xs flex-1">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Symbol e.g. BTC-USD, AAPL, RELIANCE.NS"
            className="pl-7"
          />
        </div>
        <Button type="submit" size="sm">
          Teach me
        </Button>
      </form>

      {error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(error as Error).message}
        </div>
      ) : null}

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : data ? (
        data.series.length ? (
          <div className="space-y-6">
            <PriceChart symbol={data.symbol} series={data.series} moves={data.notable_moves} />

            {/* Why it moved */}
            {data.notable_moves.length ? (
              <section className="space-y-3">
                <h2 className="font-serif text-xl tracking-tight">Why it moved</h2>
                <ul className="space-y-2">
                  {data.notable_moves.map((m) => (
                    <MoveRow key={m.date} move={m} />
                  ))}
                </ul>
              </section>
            ) : null}

            {/* Primer */}
            <section className="border border-border/60 bg-card p-5">
              <div className="mb-2 flex items-center gap-1.5">
                <GraduationCap className="h-4 w-4 text-primary" />
                <span className="eyebrow">Primer</span>
                {!data.used_llm ? (
                  <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                    · offline summary
                  </span>
                ) : null}
              </div>
              <Markdown>{data.primer_markdown}</Markdown>
            </section>

            {/* Strategies */}
            <section className="space-y-3">
              <h2 className="font-serif text-xl tracking-tight">Common strategies</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {data.strategies.map((s) => (
                  <div key={s.name} className="border border-border/60 bg-card p-4">
                    <h3 className="font-label text-xs uppercase tracking-wider text-primary">
                      {s.name}
                    </h3>
                    <p className="mt-1 text-sm leading-relaxed">{s.description}</p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      <span className="font-medium">When it helps:</span> {s.when_it_helps}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {data.disclaimer ? (
              <p className="text-[11px] text-muted-foreground">{data.disclaimer}</p>
            ) : null}
          </div>
        ) : (
          <EmptyState
            icon={GraduationCap}
            title={`No price history for ${symbol}`}
            description="Try a tracked symbol (e.g. BTC-USD, AAPL, RELIANCE.NS). The Learn view needs stored daily prices to build the chart."
          />
        )
      ) : null}
    </div>
  );
}

function PriceChart({
  symbol,
  series,
  moves,
}: {
  symbol: string;
  series: { date: string; close: number }[];
  moves: LearnMove[];
}) {
  const moveByDate = React.useMemo(() => {
    const map = new Map<string, LearnMove>();
    moves.forEach((m) => map.set(m.date, m));
    return map;
  }, [moves]);

  const closes = series.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);

  return (
    <div className="border border-border/60 bg-card p-4">
      <div className="mb-2 eyebrow">{symbol} · close ({series.length}d)</div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border/40" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
          <YAxis
            domain={[min * 0.97, max * 1.03]}
            tick={{ fontSize: 10 }}
            width={56}
            tickFormatter={(v) => Number(v).toLocaleString()}
          />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(v: number) => [Number(v).toLocaleString(), "Close"]}
          />
          <Line
            type="monotone"
            dataKey="close"
            stroke="hsl(var(--primary))"
            strokeWidth={1.75}
            dot={false}
          />
          {series.map((p) => {
            const m = moveByDate.get(p.date);
            if (!m) return null;
            return (
              <ReferenceDot
                key={p.date}
                x={p.date}
                y={p.close}
                r={5}
                fill={m.direction === "up" ? "hsl(142 71% 45%)" : "hsl(0 72% 51%)"}
                stroke="hsl(var(--background))"
                strokeWidth={1.5}
              />
            );
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function MoveRow({ move }: { move: LearnMove }) {
  const up = move.direction === "up";
  return (
    <li className="flex items-start gap-3 border border-border/60 bg-card p-4">
      <div
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          up
            ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
            : "bg-red-500/10 text-red-700 dark:text-red-400",
        )}
      >
        {up ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-mono text-sm tabular-nums">{move.date}</span>
          <span
            className={cn(
              "font-mono text-sm font-semibold tabular-nums",
              up ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400",
            )}
          >
            {move.move_pct > 0 ? "+" : ""}
            {move.move_pct.toFixed(1)}%
          </span>
        </div>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{move.explanation}</p>
        {move.catalyst?.url ? (
          <Link
            href={move.catalyst.url as never}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />
            Read the source
          </Link>
        ) : null}
      </div>
    </li>
  );
}
