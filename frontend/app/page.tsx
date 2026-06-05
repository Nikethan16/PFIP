"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Banknote,
  Bitcoin,
  ExternalLink,
  Newspaper,
  PieChart,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

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
import { Sparkline } from "@/components/charts/sparkline";
import { Kpi } from "@/components/shared/kpi";
import { RegimeBadge } from "@/components/shared/regime-badge";
import { SentimentDot } from "@/components/shared/sentiment-dot";
import { StaleBadge } from "@/components/shared/stale-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { WelcomeModal } from "@/components/shared/welcome-modal";
import { PageHeader } from "@/components/shared/page-header";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import { ChangesTodayCard } from "@/components/dashboard/changes-today-card";
import {
  useAssetNews,
  useAssetRegime,
  useCandles,
  usePortfolioSummary,
  useVarPanel,
  useWatchlist,
} from "@/lib/api";
import { cn, formatIST, formatINR, formatPct } from "@/lib/utils";
import type { Timeframe } from "@/lib/contracts";

const PRIMARY_ASSET = "BTC-USD";
const TRACKED_MARKETS = [
  { symbol: "BTC-USD", label: "Bitcoin", icon: Bitcoin },
  { symbol: "ETH-USD", label: "Ethereum", icon: Bitcoin },
  { symbol: "SPY", label: "S&P 500", icon: PieChart },
  { symbol: "NIFTY50", label: "Nifty 50", icon: PieChart },
];

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
      <WelcomeModal />
      <PageHeader
        title="Dashboard"
        description="Good morning. Here's what changed overnight."
      />

      {/* Hero KPI strip */}
      <HeroKpis />

      {/* Morning brief — hero card */}
      <BriefCard />

      {/* Charts + regime per market */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <BTCCard />
        <RegimeStack />
      </div>

      {/* What changed today — pre-empts "anything worth looking at?" */}
      <ChangesTodayCard />

      {/* Watchlist + risk */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <WatchlistMoversCard />
        <RiskSnapshotCard />
      </div>

      {/* News feed grid */}
      <NewsRow />
    </div>
  );
}

// --- Hero KPI strip ---------------------------------------------------------

function HeroKpis() {
  const { data: summary, isLoading } = usePortfolioSummary();
  const { data: risk } = useVarPanel();
  const { data: regime } = useAssetRegime(PRIMARY_ASSET);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Kpi
        label="Net worth (INR)"
        value={summary ? formatINR(summary.total_inr) : "—"}
        deltaPct={summary?.pnl_pct ?? null}
        hint={summary ? `vs cost basis` : null}
        icon={<Banknote className="h-3.5 w-3.5" />}
        loading={isLoading}
        freshness={summary ? "fresh" : undefined}
      />
      <Kpi
        label="Today's P&L"
        value={risk ? formatINR(risk.day_change_inr) : "—"}
        deltaPct={risk?.day_change_pct ?? null}
        icon={<TrendingUp className="h-3.5 w-3.5" />}
        loading={isLoading}
        freshness={risk ? "fresh" : undefined}
      />
      <Kpi
        label="BTC regime"
        value={
          regime ? (
            <RegimeBadge regime={regime.regime} size="md" />
          ) : (
            "—"
          )
        }
        hint={regime ? `${Math.round(regime.confidence * 100)}% conf` : null}
        tone="neutral"
        icon={<Bitcoin className="h-3.5 w-3.5" />}
        loading={isLoading}
      />
      <Kpi
        label="Drawdown"
        freshness={
          summary == null
            ? undefined
            : summary.drawdown_pct <= -15
              ? "failing"
              : summary.drawdown_pct <= -5
                ? "stale"
                : "fresh"
        }
        value={summary ? formatPct(summary.drawdown_pct) : "—"}
        tone={
          summary == null
            ? "neutral"
            : summary.drawdown_pct <= -10
              ? "down"
              : summary.drawdown_pct >= 0
                ? "up"
                : "neutral"
        }
        hint={
          risk
            ? `${risk.daily_new_positions_remaining ?? 0} new positions left`
            : null
        }
        icon={<ShieldAlert className="h-3.5 w-3.5" />}
        loading={isLoading}
      />
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
  const positive = (changePct ?? 0) >= 0;

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bitcoin className="h-4 w-4 text-amber-500" />
            BTC-USD
            <FreshnessBadge sources={["coinbase_ohlcv", "ccxt_BTC_USD"]} />
          </CardTitle>
          <CardDescription>Spot · past {tf.toLowerCase()}</CardDescription>
        </div>
        {last ? (
          <div className="text-right">
            <div className="font-num text-xl font-semibold tracking-tight">
              {new Intl.NumberFormat("en-US", {
                style: "currency",
                currency: "USD",
                maximumFractionDigits: 2,
              }).format(last.close)}
            </div>
            {changePct != null ? (
              <div
                className={cn(
                  "flex items-center justify-end gap-1 text-xs font-medium",
                  positive
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-600 dark:text-red-400",
                )}
              >
                {positive ? (
                  <TrendingUp className="h-3 w-3" />
                ) : (
                  <TrendingDown className="h-3 w-3" />
                )}
                <span className="font-num">{formatPct(changePct)}</span>
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
                description="The ingestion flow hasn't populated this timeframe yet. Run /flows/ingest_market_data from the backend to backfill."
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

// --- Regime stack: one row per tracked market with sparkline ----------------

function RegimeStack() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          Markets at a glance
          <FreshnessBadge sources={["regime_hmm_daily"]} />
        </CardTitle>
        <CardDescription>Regime + 30-day trend per tracked market.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-1">
        {TRACKED_MARKETS.map((m) => (
          <RegimeStackRow key={m.symbol} symbol={m.symbol} label={m.label} />
        ))}
      </CardContent>
    </Card>
  );
}

function RegimeStackRow({ symbol, label }: { symbol: string; label: string }) {
  const { data: regime } = useAssetRegime(symbol);
  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 30);
    return d.toISOString();
  }, []);
  const { data: candles } = useCandles({
    symbol,
    timeframe: "1d",
    since,
  });
  const closes = (candles ?? []).map((c) => c.close);
  const last = closes[closes.length - 1];
  const first = closes[0];
  const change = first && last ? ((last - first) / first) * 100 : null;

  return (
    <div className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover-tile">
      <div className="flex min-w-0 items-center gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{label}</div>
          <div className="font-mono text-[10px] text-muted-foreground">
            {symbol}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Sparkline values={closes} width={64} height={24} ariaLabel={`${label} 30d`} />
        <div className="text-right">
          {regime ? (
            <RegimeBadge regime={regime.regime} />
          ) : (
            <span className="text-[10px] text-muted-foreground">—</span>
          )}
          <div
            className={cn(
              "mt-0.5 font-num text-[11px]",
              (change ?? 0) >= 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-600 dark:text-red-400",
            )}
          >
            {change != null ? `${formatPct(change)} 30d` : "—"}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Watchlist movers -------------------------------------------------------

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
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base flex items-center gap-2">
            Watchlist movers
            <FreshnessBadge sources={["yfinance_eod", "jugaad_eod"]} />
          </CardTitle>
          <CardDescription>Top 3 gainers + losers, 24h.</CardDescription>
        </div>
        <Link
          href={"/watchlist" as never}
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          Manage <ArrowUpRight className="h-3 w-3" />
        </Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="text-xs text-destructive">
            Couldn&apos;t load watchlist.
          </div>
        ) : !data?.length ? (
          <EmptyState
            title="No watchlist items yet"
            description="Add a few symbols to get overnight movers here."
            action={{ label: "Add symbols", href: "/watchlist" }}
          />
        ) : !gainers.length && !losers.length ? (
          <EmptyState
            title="No 24h data yet"
            description="Once ingest runs at 05:35 IST this will populate."
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
      <div className={cn("mb-1.5 flex items-center gap-1 text-[10px] uppercase tracking-wider", tone)}>
        <Icon className="h-3 w-3" /> {title}
      </div>
      {!items.length ? (
        <div className="text-xs text-muted-foreground">—</div>
      ) : (
        <ul className="divide-y divide-border/60">
          {items.map((i) => (
            <li
              key={i.id}
              className="flex items-center justify-between gap-2 py-1.5"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{i.symbol}</div>
                {i.regime ? <RegimeBadge regime={i.regime} /> : null}
              </div>
              <span className={cn("font-num text-sm font-medium", tone)}>
                {formatPct(i.ch)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- Risk snapshot ----------------------------------------------------------

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
        <CardContent className="p-6">
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
  const halt = -20;
  const progress = Math.min(100, Math.max(0, (dd / halt) * 100));
  // Color the bar on the SAME drawdown thresholds as the KPI tone above, so a
  // red number never sits over a green bar (previously the bar keyed off
  // progress% which crossed at different points than ddTone).
  const ddBar =
    dd <= -10 ? "bg-red-500" : dd <= -5 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          Risk snapshot
          <FreshnessBadge sources={["portfolio_pnl_daily"]} />
        </CardTitle>
        <CardDescription>
          Drawdown vs halt threshold, daily caps, day P&amp;L.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-md border bg-muted/30 p-2.5">
            <div className="eyebrow">Total value</div>
            <div className="mt-0.5 font-num text-base font-semibold tracking-tight">
              {formatINR(summary.total_inr)}
            </div>
          </div>
          <div className="rounded-md border bg-muted/30 p-2.5">
            <div className="eyebrow">Drawdown</div>
            <div className={cn("mt-0.5 font-num text-base font-semibold tracking-tight", ddTone)}>
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
                "absolute inset-y-0 left-0 rounded transition-all duration-500",
                ddBar,
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
            <div className="text-muted-foreground">New positions left</div>
            <div className="font-num text-base font-semibold tabular-nums">
              {risk?.daily_new_positions_remaining ?? "—"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">Day change</div>
            <div
              className={cn(
                "font-num text-base font-semibold tabular-nums",
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

// --- News grid (per tracked market) ----------------------------------------

function NewsRow() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base flex items-center gap-2">
            <Newspaper className="h-4 w-4 text-muted-foreground" />
            Top news
            <FreshnessBadge sources={["news_rss", "gdelt"]} />
          </CardTitle>
          <CardDescription>
            Latest headlines per tracked asset with sentiment.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {TRACKED_MARKETS.map((m) => (
            <NewsColumn key={m.symbol} symbol={m.symbol} label={m.label} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function NewsColumn({ symbol, label }: { symbol: string; label: string }) {
  const { data, isLoading } = useAssetNews(symbol);
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-xs font-medium">{label}</div>
          <div className="font-mono text-[10px] text-muted-foreground">
            {symbol}
          </div>
        </div>
      </div>
      {isLoading ? (
        <div className="space-y-1.5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : !data?.length ? (
        <div className="rounded border border-dashed p-3 text-center text-[11px] text-muted-foreground">
          No recent news.
        </div>
      ) : (
        <ul className="space-y-1.5">
          {data.slice(0, 5).map((item) => (
            <li
              key={item.id}
              className="rounded-md border bg-card p-2 hover-tile"
            >
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group block"
              >
                <div className="mb-1 flex items-center justify-between gap-1">
                  <SentimentDot value={item.sentiment ?? null} size="xs" />
                  <ExternalLink className="h-3 w-3 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
                <div className="line-clamp-2 text-xs font-medium leading-snug group-hover:text-primary">
                  {item.title}
                </div>
                <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
                  <span className="truncate">{item.source}</span>
                  <span>{formatIST(item.published_at, "dd MMM HH:mm")}</span>
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
