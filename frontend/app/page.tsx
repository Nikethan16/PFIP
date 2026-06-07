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

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BriefCard } from "@/components/morning-brief/brief-card";
import { Sparkline } from "@/components/charts/sparkline";
import { Kpi } from "@/components/shared/kpi";
import { RegimeBadge } from "@/components/shared/regime-badge";
import { SentimentDot } from "@/components/shared/sentiment-dot";
import { EmptyState } from "@/components/shared/empty-state";
import { WelcomeModal } from "@/components/shared/welcome-modal";
import { PageHeader } from "@/components/shared/page-header";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import { ChangesTodayCard } from "@/components/dashboard/changes-today-card";
import { PriceChartCard } from "@/components/dashboard/price-chart-card";
import { RegimeStatePanel } from "@/components/dashboard/regime-state-panel";
import { DigestCards } from "@/components/dashboard/digest-cards";
import {
  useAssetNews,
  useAssetRegime,
  useCandles,
  usePortfolioSummary,
  useVarPanel,
  useWatchlist,
} from "@/lib/api";
import type { HoldingCategory } from "@/lib/contracts";
import { cn, formatIST, formatINR, formatPct } from "@/lib/utils";

const PRIMARY_ASSET = "BTC-USD";
const TRACKED_MARKETS = [
  { symbol: "BTC-USD", label: "Bitcoin", icon: Bitcoin },
  { symbol: "ETH-USD", label: "Ethereum", icon: Bitcoin },
  { symbol: "SPY", label: "S&P 500", icon: PieChart },
  { symbol: "NIFTYBEES.NS", label: "Nifty 50 ETF", icon: PieChart },
];

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      <WelcomeModal />
      <PageHeader
        title="Terminal"
        description="Good morning. Here's what changed overnight."
      />

      {/* 1 — Top KPI strip */}
      <HeroKpis />

      {/* 2 — Main row: price chart (2/3) + dark regime panel (1/3) */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <PriceChartCard
          asset={PRIMARY_ASSET}
          title="BTC / USD"
          className="lg:col-span-8"
        />
        <div className="lg:col-span-4">
          <RegimeStatePanel asset={PRIMARY_ASSET} assetLabel="BTC" />
        </div>
      </div>

      {/* 3 — What Changed Today (editorial feed) + markets glance */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-8">
          <ChangesTodayCard />
          <BriefCard />
        </div>
        <div className="space-y-6 lg:col-span-4">
          <MarketsGlanceCard />
          <ExposureBento />
        </div>
      </div>

      {/* 4 — Supporting: watchlist movers + risk snapshot */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <WatchlistMoversCard />
        <RiskSnapshotCard />
      </div>

      {/* 5 — Agent digests: weekly review + arXiv research digest */}
      <DigestCards />

      {/* 6 — News feed grid */}
      <NewsRow />
    </div>
  );
}

// --- Top KPI strip ----------------------------------------------------------

/** Maps the live VaR(95%) into the Sahara "RISK STATUS" badge label. */
function riskStatus(var95Pct: number | null): { label: string; note: string } {
  if (var95Pct == null) return { label: "—", note: "" };
  const v = Math.abs(var95Pct);
  if (v >= 6) return { label: "ELEVATED", note: "HIGH VAR" };
  if (v >= 3) return { label: "MODERATE", note: "WATCH VOL" };
  return { label: "STABLE", note: "LOW VAR" };
}

function HeroKpis() {
  const { data: summary, isLoading } = usePortfolioSummary();
  const { data: risk } = useVarPanel();

  // Backend `summary.drawdown` is a 0..1 fraction (peak-to-current); render it
  // as a negative percentage.
  const drawdownPct =
    summary != null ? -Math.abs(summary.drawdown) * 100 : null;

  const status = riskStatus(risk ? risk.var_95_pct : null);
  const pnlPositive = (risk?.day_change_inr ?? 0) >= 0;

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Kpi
        label="Net Worth"
        value={summary ? formatINR(summary.total_inr) : "—"}
        deltaPct={summary?.pnl_pct ?? null}
        hint={summary ? `vs cost basis` : null}
        icon={<Banknote className="h-3.5 w-3.5" />}
        loading={isLoading}
        freshness={summary ? "fresh" : undefined}
      />
      <Kpi
        label="Total P&L (today)"
        value={risk ? formatINR(risk.day_change_inr) : "—"}
        valueClassName={
          risk == null
            ? undefined
            : pnlPositive
              ? "text-emerald-700 dark:text-emerald-400"
              : "text-red-700 dark:text-red-400"
        }
        deltaPct={risk?.day_change_pct ?? null}
        icon={<TrendingUp className="h-3.5 w-3.5" />}
        loading={isLoading}
        freshness={risk ? "fresh" : undefined}
      />
      <Kpi
        label="Max Drawdown"
        freshness={
          drawdownPct == null
            ? undefined
            : drawdownPct <= -15
              ? "failing"
              : drawdownPct <= -5
                ? "stale"
                : "fresh"
        }
        value={drawdownPct != null ? formatPct(drawdownPct) : "—"}
        tone={
          drawdownPct == null
            ? "neutral"
            : drawdownPct <= -10
              ? "down"
              : drawdownPct >= 0
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
      <Kpi
        label="Risk Status"
        accent
        value={status.label}
        tone="neutral"
        valueClassName="text-primary"
        hint={status.note || null}
        icon={<ShieldAlert className="h-3.5 w-3.5" />}
        loading={isLoading}
      />
    </div>
  );
}

// --- Markets at a glance (per tracked market with sparkline) -----------------

function MarketsGlanceCard() {
  return (
    <section className="border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow flex items-center gap-2">
          Markets at a glance
          <FreshnessBadge sources={["regime_hmm_daily"]} />
        </div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">
          Regime &amp; 30-day trend
        </h3>
      </div>
      <div className="divide-y divide-border/40">
        {TRACKED_MARKETS.map((m) => (
          <MarketsGlanceRow key={m.symbol} symbol={m.symbol} label={m.label} />
        ))}
      </div>
    </section>
  );
}

function MarketsGlanceRow({
  symbol,
  label,
}: {
  symbol: string;
  label: string;
}) {
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
    <div className="flex items-center justify-between gap-2 px-5 py-3 hover-tile">
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">{label}</div>
        <div className="font-mono text-[10px] text-muted-foreground">
          {symbol}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Sparkline
          values={closes}
          width={64}
          height={24}
          ariaLabel={`${label} 30d`}
        />
        <div className="text-right">
          {regime ? (
            <RegimeBadge regime={regime.regime} />
          ) : (
            <span className="text-[10px] text-muted-foreground">—</span>
          )}
          <div
            className={cn(
              "mt-0.5 font-mono text-[11px] tabular-nums",
              (change ?? 0) >= 0
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-red-700 dark:text-red-400",
            )}
          >
            {change != null ? `${formatPct(change)} 30d` : "—"}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Exposure bento (portfolio mix by category) -----------------------------

const CATEGORY_LABELS: Partial<Record<HoldingCategory, string>> = {
  equity: "Equity",
  etf: "ETFs",
  mutual_fund: "Mutual funds",
  crypto_exchange: "Crypto",
  crypto_self_custody: "Crypto (cold)",
  cash: "Cash",
  fd: "Fixed deposits",
  ppf: "PPF",
  epf: "EPF",
  nps: "NPS",
  sgb: "Sovereign gold",
  gsec: "G-secs",
  bond: "Bonds",
};

function ExposureBento() {
  const { data: summary, isLoading } = usePortfolioSummary();

  const slices = React.useMemo(() => {
    if (!summary) return [];
    const entries = Object.entries(summary.exposure_by_category) as Array<
      [HoldingCategory, number]
    >;
    const total = entries.reduce((acc, [, v]) => acc + (v ?? 0), 0);
    if (total <= 0) return [];
    return entries
      .map(([cat, v]) => ({
        cat,
        label: CATEGORY_LABELS[cat] ?? cat,
        pct: (v / total) * 100,
      }))
      .sort((a, b) => b.pct - a.pct)
      .slice(0, 3);
  }, [summary]);

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="col-span-2 h-28 w-full" />
      </div>
    );
  }

  if (!slices.length) return null;

  return (
    <div className="grid grid-cols-2 gap-4">
      {slices.map((s, i) => (
        <div
          key={s.cat}
          className={cn(
            "flex h-28 flex-col justify-between border border-border/50 bg-secondary/40 p-4",
            i === 2 && "col-span-2",
          )}
        >
          <div className="flex items-start justify-between">
            <span className="eyebrow">{s.label}</span>
            {i === 0 ? (
              <TrendingUp className="h-3.5 w-3.5 text-primary" />
            ) : null}
          </div>
          <span className="font-mono text-lg font-semibold tabular-nums">
            {s.pct.toFixed(1)}%
          </span>
        </div>
      ))}
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
    <section className="border border-border/60 bg-card">
      <div className="flex flex-row items-center justify-between gap-3 border-b border-border/40 p-5">
        <div>
          <div className="eyebrow flex items-center gap-2">
            Watchlist movers
            <FreshnessBadge sources={["yfinance_eod", "jugaad_eod"]} />
          </div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Top movers · 24h
          </h3>
        </div>
        <Link
          href={"/watchlist" as never}
          className="inline-flex items-center gap-1 font-label text-xs uppercase tracking-wider text-primary hover:underline"
        >
          Manage <ArrowUpRight className="h-3 w-3" />
        </Link>
      </div>
      <div className="p-5">
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
      </div>
    </section>
  );
}

function MoverList({
  title,
  items,
  up,
}: {
  title: string;
  items: Array<{
    id?: string | null;
    symbol: string;
    label?: string | null;
    ch: number;
    regime?: import("@/lib/contracts").Regime | null;
  }>;
  up: boolean;
}) {
  const Icon = up ? TrendingUp : TrendingDown;
  const tone = up
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-red-700 dark:text-red-400";
  return (
    <div>
      <div
        className={cn(
          "mb-1.5 flex items-center gap-1 font-label text-[10px] uppercase tracking-wider",
          tone,
        )}
      >
        <Icon className="h-3 w-3" /> {title}
      </div>
      {!items.length ? (
        <div className="text-xs text-muted-foreground">—</div>
      ) : (
        <ul className="divide-y divide-border/50">
          {items.map((i) => (
            <li
              key={i.id ?? i.symbol}
              className="flex items-center justify-between gap-2 py-1.5"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{i.symbol}</div>
                {i.regime ? <RegimeBadge regime={i.regime} /> : null}
              </div>
              <span className={cn("font-mono text-sm font-medium tabular-nums", tone)}>
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
      <section className="border border-border/60 bg-card p-6">
        <div className="space-y-3">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-3 w-full" />
        </div>
      </section>
    );
  }

  if (!summary) {
    return (
      <section className="border border-border/60 bg-card p-6">
        <EmptyState
          title="Portfolio empty"
          description="Import CSVs from the Tax page to begin tracking drawdown + risk."
          action={{ label: "Go to tax imports", href: "/tax" }}
        />
      </section>
    );
  }

  // `summary.drawdown` is a 0..1 fraction; show it as a negative percentage.
  const dd = -Math.abs(summary.drawdown) * 100;
  const ddTone =
    dd <= -10
      ? "text-red-700 dark:text-red-400"
      : dd <= -5
        ? "text-amber-700 dark:text-amber-400"
        : "text-emerald-700 dark:text-emerald-400";
  const halt = -20;
  const progress = Math.min(100, Math.max(0, (dd / halt) * 100));
  // Color the bar on the SAME drawdown thresholds as the tone above, so a red
  // number never sits over a green bar.
  const ddBar =
    dd <= -10 ? "bg-red-500" : dd <= -5 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <section className="border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow flex items-center gap-2">
          Risk snapshot
          <FreshnessBadge sources={["portfolio_pnl_daily"]} />
        </div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">
          Drawdown &amp; daily caps
        </h3>
      </div>
      <div className="space-y-4 p-5">
        <div className="grid grid-cols-2 gap-3">
          <div className="border border-border/50 bg-secondary/40 p-3">
            <div className="eyebrow">Total value</div>
            <div className="mt-0.5 font-mono text-base font-semibold tracking-tight tabular-nums">
              {formatINR(summary.total_inr)}
            </div>
          </div>
          <div className="border border-border/50 bg-secondary/40 p-3">
            <div className="eyebrow">Drawdown</div>
            <div
              className={cn(
                "mt-0.5 font-mono text-base font-semibold tracking-tight tabular-nums",
                ddTone,
              )}
            >
              {formatPct(dd)}
            </div>
          </div>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between font-label text-[11px] uppercase tracking-wider text-muted-foreground">
            <span>0%</span>
            <span>Halt @ {halt}%</span>
          </div>
          <div className="relative h-2 w-full bg-muted">
            <div
              className={cn(
                "absolute inset-y-0 left-0 transition-all duration-500",
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
            <div className="eyebrow">New positions left</div>
            <div className="mt-0.5 font-mono text-base font-semibold tabular-nums">
              {risk?.daily_new_positions_remaining ?? "—"}
            </div>
          </div>
          <div>
            <div className="eyebrow">Day change</div>
            <div
              className={cn(
                "mt-0.5 font-mono text-base font-semibold tabular-nums",
                (risk?.day_change_inr ?? 0) >= 0
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-red-700 dark:text-red-400",
              )}
            >
              {risk
                ? `${formatINR(risk.day_change_inr)} (${formatPct(risk.day_change_pct)})`
                : "—"}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end">
          <Button asChild size="sm" variant="outline">
            <Link href={"/portfolio" as never}>Open portfolio</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

// --- News grid (per tracked market) ----------------------------------------

function NewsRow() {
  return (
    <section className="border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow flex items-center gap-2">
          <Newspaper className="h-3.5 w-3.5" />
          Top news
          <FreshnessBadge sources={["news_rss", "gdelt"]} />
        </div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">
          Headlines &amp; sentiment
        </h3>
      </div>
      <div className="p-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {TRACKED_MARKETS.map((m) => (
            <NewsColumn key={m.symbol} symbol={m.symbol} label={m.label} />
          ))}
        </div>
      </div>
    </section>
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
        <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
          No recent news.
        </div>
      ) : (
        <ul className="space-y-1.5">
          {data.slice(0, 5).map((item, i) => (
            <li
              key={item.id ?? `${item.url}-${i}`}
              className="border border-border/50 bg-secondary/30 p-2 hover-tile"
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
                <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-muted-foreground">
                  <span className="truncate">{item.source}</span>
                  <span>{formatIST(item.time, "dd MMM HH:mm")}</span>
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
