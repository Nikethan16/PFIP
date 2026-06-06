"use client";

/**
 * Sahara "BTC / USD" price-chart card.
 *
 * Owns the timeframe toggle + candle fetch for the primary asset and renders
 * the editorial chrome from the mockup: serif title, mono price/volume readout,
 * 1D/1W/1M/3M/1Y toggles, the amber area chart, and an ADVISORY footer.
 *
 * IMPORTANT: this is an advisory-only product. The mockup's "Execute Trade"
 * row is intentionally replaced with non-execution actions — "Open in Signals"
 * and "Ask the agent" — so nothing here implies order placement.
 */

import * as React from "react";
import Link from "next/link";
import { Bitcoin, MessageSquareText, TrendingDown, TrendingUp } from "lucide-react";

import { CandleChart } from "@/components/charts/candle-chart";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import { StaleBadge } from "@/components/shared/stale-badge";
import { useCandles } from "@/lib/api";
import type { Timeframe } from "@/lib/contracts";
import { cn, formatPct } from "@/lib/utils";

type DashboardTimeframe = "1D" | "1W" | "1M" | "3M" | "1Y";

const TIMEFRAMES: readonly DashboardTimeframe[] = [
  "1D",
  "1W",
  "1M",
  "3M",
  "1Y",
] as const;

const TIMEFRAME_MAP: Record<
  DashboardTimeframe,
  { timeframe: Timeframe; sinceDays: number }
> = {
  "1D": { timeframe: "1h", sinceDays: 1 },
  "1W": { timeframe: "1h", sinceDays: 7 },
  "1M": { timeframe: "1d", sinceDays: 30 },
  "3M": { timeframe: "1d", sinceDays: 90 },
  "1Y": { timeframe: "1d", sinceDays: 365 },
};

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

/** Compact volume readout, e.g. 1.2B / 845.0M / 12.4K. */
function formatVolume(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

interface PriceChartCardProps {
  asset: string;
  /** Display label, e.g. "BTC / USD". */
  title?: string;
  /** Source adapter names for the freshness dot. */
  sources?: string[];
  className?: string;
}

export function PriceChartCard({
  asset,
  title = "BTC / USD",
  sources = ["coinbase_ohlcv", "ccxt_BTC_USD"],
  className,
}: PriceChartCardProps) {
  const [tf, setTf] = React.useState<DashboardTimeframe>("1M");
  const cfg = TIMEFRAME_MAP[tf];

  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - cfg.sinceDays);
    return d.toISOString();
  }, [cfg.sinceDays]);

  const { data, isLoading, error } = useCandles({
    symbol: asset,
    timeframe: cfg.timeframe,
    since,
  });

  const last = data?.[data.length - 1];
  const first = data?.[0];
  const changePct =
    last && first ? ((last.close - first.close) / first.close) * 100 : null;
  const positive = (changePct ?? 0) >= 0;

  return (
    <div
      className={cn(
        "flex flex-col border border-border/60 bg-card",
        className,
      )}
    >
      {/* Header: serif title + mono price/vol readout + timeframe toggles. */}
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/40 p-6">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-serif text-2xl tracking-tight">
            <Bitcoin className="h-5 w-5 text-primary" />
            {title}
            <FreshnessBadge sources={sources} />
          </h2>
          <p className="mt-1 font-mono text-sm text-muted-foreground">
            {last ? (
              <>
                Price:{" "}
                <span className="font-semibold text-foreground">
                  {usdFmt.format(last.close)}
                </span>
                <span className="ml-3">Vol: {formatVolume(last.volume)}</span>
              </>
            ) : (
              <span className="eyebrow">Spot · past {tf.toLowerCase()}</span>
            )}
          </p>
        </div>

        <div className="flex flex-col items-end gap-2">
          {changePct != null ? (
            <div
              className={cn(
                "flex items-center gap-1 font-mono text-xs font-medium tabular-nums",
                positive
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-red-700 dark:text-red-400",
              )}
            >
              {positive ? (
                <TrendingUp className="h-3 w-3" />
              ) : (
                <TrendingDown className="h-3 w-3" />
              )}
              {formatPct(changePct)}
              <span className="text-muted-foreground/70"> · {tf}</span>
            </div>
          ) : null}
          <div className="flex gap-1.5" role="tablist" aria-label="Chart timeframe">
            {TIMEFRAMES.map((t) => {
              const active = t === tf;
              return (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setTf(t)}
                  className={cn(
                    "border px-2.5 py-1 font-mono text-xs transition-colors",
                    active
                      ? "border-foreground bg-foreground text-background"
                      : "border-border/50 bg-transparent text-muted-foreground hover:border-foreground/40 hover:text-foreground",
                  )}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Chart body. */}
      <div className="flex-1 p-4">
        {isLoading ? (
          <Skeleton className="h-[300px] w-full" />
        ) : error ? (
          <div className="flex h-[300px] flex-col items-center justify-center border border-destructive/40 bg-destructive/5 p-6 text-center text-xs text-destructive">
            Couldn&apos;t load candles. {(error as Error).message}
          </div>
        ) : !data?.length ? (
          <EmptyState
            title="No candle data"
            description="The ingestion flow hasn't populated this timeframe yet. Run /flows/ingest_market_data from the backend to backfill."
          />
        ) : (
          <CandleChart data={data} height={300} />
        )}
      </div>

      {/* Advisory footer — replaces the mockup's trade buttons. */}
      <div className="flex flex-wrap items-center gap-3 border-t border-border/40 bg-secondary/40 p-4">
        <Link
          href={"/signals" as never}
          className="flex flex-1 items-center justify-center gap-2 bg-primary px-4 py-3 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
        >
          <TrendingUp className="h-4 w-4" />
          Open in Signals
        </Link>
        <Link
          href={"/chat" as never}
          className="flex items-center justify-center gap-2 border border-border px-6 py-3 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
        >
          <MessageSquareText className="h-4 w-4" />
          Ask the agent
        </Link>
        {last ? (
          <StaleBadge updatedAt={last.time} className="ml-auto" />
        ) : null}
      </div>
    </div>
  );
}
