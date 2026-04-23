"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, TrendingDown, TrendingUp } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import { BriefCard } from "@/components/morning-brief/brief-card";
import { CandleChart } from "@/components/charts/candle-chart";
import { RegimeBadge } from "@/components/shared/regime-badge";
import { StaleBadge } from "@/components/shared/stale-badge";
import { EmptyState } from "@/components/shared/empty-state";
import {
  useAssetRegime,
  useCandles,
  usePortfolioSummary,
  useVarPanel,
  useWatchlist,
} from "@/lib/api";
import { cn, formatINR, formatPct } from "@/lib/utils";
import type { Timeframe } from "@/lib/contracts";

const PRIMARY_ASSET = "BTC-USD";

type DashboardTimeframe = "1D" | "1W" | "1M" | "3M" | "1Y";

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

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Good morning. Here&apos;s what changed overnight.
        </p>
      </div>

      <BriefCard />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <BTCCard />
        <RegimeCard />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <WatchlistMoversCard />
        <RiskSnapshotCard />
      </div>
    </div>
  );
}

// --- BTC card with timeframe toggle -----------------------------------------

function BTCCard() {
  const [tf, setTf] = React.useState<DashboardTimeframe>("1M");
  const cfg = TIMEFRAME_MAP[tf];

  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - cfg.sinceDays);
    return d.toISOString();
  }, [cfg.sinceDays]);

  const { data, isLoading, error } = useCandles({
    symbol: PRIMARY_ASSET,
    timeframe: cfg.timeframe,
    since,
  });

  const last = data?.[data.length - 1];
  const first = data?.[0];
  const changePct =
    last && first ? ((last.close - first.close) / first.close) * 100 : null;

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex flex-row items-start justify-between">
        <div>
          <CardTitle>BTC-USD</CardTitle>
          <CardDescription>Spot · past {tf.toLowerCase()}</CardDescription>
        </div>
        {last ? (
          <div className="text-right">
            <div className="text-lg font-semibold tabular-nums">
              {new Intl.NumberFormat("en-US", {
                style: "currency",
                currency: "USD",
                maximumFractionDigits: 2,
              }).format(last.close)}
            </div>
            {changePct != null ? (
              <div
                className={cn(
                  "text-xs",
                  changePct >= 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-600 dark:text-red-400",
                )}
              >
                {formatPct(changePct)}
              </div>
            ) : null}
            <StaleBadge updatedAt={last.time} className="mt-1 justify-end" />
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        <Tabs value={tf} onValueChange={(v) => setTf(v as DashboardTimeframe)}>
          <TabsList className="h-8">
            {(["1D", "1W", "1M", "3M", "1Y"] as const).map((t) => (
              <TabsTrigger key={t} value={t} className="h-7 px-3 text-xs">
                {t}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value={tf} className="mt-3">
            {isLoading ? (
              <Skeleton className="h-[280px] w-full" />
            ) : error ? (
              <div className="flex h-[280px] flex-col items-center justify-center rounded-md border border-destructive/40 bg-destructive/5 p-6 text-center text-xs text-destructive">
                Couldn&apos;t load candles. {(error as Error).message}
              </div>
            ) : !data?.length ? (
              <EmptyState
                title="No candle data"
                description="The ingestion flow hasn't populated this timeframe yet."
              />
            ) : (
              <CandleChart data={data} />
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

// --- Regime card ------------------------------------------------------------

function RegimeCard() {
  const { data, isLoading, error } = useAssetRegime(PRIMARY_ASSET);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Market regime</CardTitle>
        <CardDescription>BTC-USD regime classifier</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : error ? (
          <div className="text-xs text-destructive">Regime unavailable.</div>
        ) : data ? (
          <div className="space-y-3">
            <RegimeBadge
              regime={data.regime}
              size="md"
              showConfidence={data.confidence}
            />
            <div className="text-xs text-muted-foreground">
              Since {new Date(data.since).toLocaleDateString()}
            </div>
            <div className="text-xs">
              Confidence:{" "}
              <span className="font-medium">
                {Math.round(data.confidence * 100)}%
              </span>
            </div>
            <StaleBadge updatedAt={data.since} />
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            Regime unavailable.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --- Watchlist top 3 gainers/losers ----------------------------------------

function WatchlistMoversCard() {
  const { data, isLoading, error } = useWatchlist();

  const { gainers, losers } = React.useMemo(() => {
    const scored = (data ?? [])
      .filter((i) => i.change_pct_24h != null)
      .map((i) => ({ ...i, ch: i.change_pct_24h ?? 0 }));
    const sorted = [...scored].sort((a, b) => b.ch - a.ch);
    return {
      gainers: sorted.slice(0, 3),
      losers: sorted.slice(-3).reverse(),
    };
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Watchlist movers · 24h</CardTitle>
          <CardDescription>Top 3 gainers + top 3 losers</CardDescription>
        </div>
        <Link
          href={"/watchlist" as never}
          className="flex items-center gap-1 text-xs text-primary hover:underline"
        >
          Manage <ArrowUpRight className="h-3 w-3" />
        </Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : error ? (
          <div className="text-xs text-destructive">Couldn&apos;t load watchlist.</div>
        ) : !data?.length ? (
          <EmptyState
            title="No watchlist items yet"
            description="Add a few symbols to get overnight movers here."
            action={{ label: "Add symbols", href: "/watchlist" }}
          />
        ) : !gainers.length && !losers.length ? (
          <EmptyState
            title="No 24h data yet"
            description="Waiting on the next market-data tick."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <MoverList title="Gainers" items={gainers} up />
            <MoverList title="Losers" items={losers} up={false} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MoverList({
  title,
  items,
  up,
}: {
  title: string;
  items: Array<{
    id: string;
    symbol: string;
    label?: string | null;
    ch: number;
    regime?: import("@/lib/contracts").Regime | null;
  }>;
  up: boolean;
}) {
  const Icon = up ? TrendingUp : TrendingDown;
  const tone = up
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";
  return (
    <div>
      <div className={cn("mb-1 flex items-center gap-1 text-xs", tone)}>
        <Icon className="h-3 w-3" /> {title}
      </div>
      {!items.length ? (
        <div className="text-xs text-muted-foreground">—</div>
      ) : (
        <ul className="divide-y">
          {items.map((i) => (
            <li key={i.id} className="flex items-center justify-between py-1.5">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{i.symbol}</div>
                {i.regime ? <RegimeBadge regime={i.regime} /> : null}
              </div>
              <span className={cn("text-sm tabular-nums", tone)}>
                {formatPct(i.ch)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- Risk snapshot card -----------------------------------------------------

function RiskSnapshotCard() {
  const { data: summary, isLoading: loadingSummary } = usePortfolioSummary();
  const { data: risk, isLoading: loadingRisk } = useVarPanel();

  if (loadingSummary || loadingRisk) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-3 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!summary) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            title="Portfolio empty"
            description="Import CSVs from the Tax page to begin tracking drawdown + risk."
            action={{ label: "Go to tax imports", href: "/tax" }}
          />
        </CardContent>
      </Card>
    );
  }

  const dd = summary.drawdown_pct;
  const ddTone =
    dd <= -10
      ? "text-red-600 dark:text-red-400"
      : dd <= -5
        ? "text-amber-600 dark:text-amber-400"
        : "text-emerald-600 dark:text-emerald-400";
  // Drawdown bar: negative % of halt threshold. Default halt at -20%.
  const halt = -20;
  const progress = Math.min(100, Math.max(0, (dd / halt) * 100));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Risk snapshot</CardTitle>
        <CardDescription>
          Drawdown, daily caps, total value
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Total value
            </div>
            <div className="text-base font-semibold tabular-nums">
              {formatINR(summary.total_inr)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Drawdown
            </div>
            <div className={cn("text-base font-semibold tabular-nums", ddTone)}>
              {formatPct(dd)}
            </div>
          </div>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>0%</span>
            <span>Halt @ {halt}%</span>
          </div>
          <div className="relative h-2 w-full rounded bg-muted">
            <div
              className={cn(
                "absolute inset-y-0 left-0 rounded transition-all",
                progress >= 80
                  ? "bg-red-500"
                  : progress >= 50
                    ? "bg-amber-500"
                    : "bg-emerald-500",
              )}
              style={{ width: `${progress}%` }}
              role="progressbar"
              aria-label="Drawdown progress toward halt"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <div className="text-muted-foreground">New positions left today</div>
            <div className="font-semibold tabular-nums">
              {risk?.daily_new_positions_remaining ?? "—"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">Day change</div>
            <div
              className={cn(
                "font-semibold tabular-nums",
                (risk?.day_change_inr ?? 0) >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-red-600 dark:text-red-400",
              )}
            >
              {risk
                ? `${formatINR(risk.day_change_inr)} (${formatPct(risk.day_change_pct)})`
                : "—"}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <StaleBadge updatedAt={summary.updated_at} />
          <Button asChild size="sm" variant="outline">
            <Link href={"/portfolio" as never}>Open portfolio</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
