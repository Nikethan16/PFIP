"use client";

/**
 * Net Worth — consolidated wealth across every asset class.
 *
 * Liquid holdings (equity/crypto/ETF) are marked to their latest close; illiquid
 * / manual assets (PPF, EPF, NPS, FD, SGB, G-Sec, bonds, cash) are held at cost
 * basis. Data: useNetWorth() → GET /portfolio/net-worth. Observational only.
 */

import * as React from "react";
import { Layers, TrendingUp, Wallet } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { Kpi } from "@/components/shared/kpi";
import { EmptyState } from "@/components/shared/empty-state";
import { useNetWorth } from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";

const CATEGORY_LABELS: Record<string, string> = {
  equity: "Equity",
  etf: "ETF",
  mutual_fund: "Mutual funds",
  crypto_exchange: "Crypto (exchange)",
  crypto_self_custody: "Crypto (self-custody)",
  ppf: "PPF",
  epf: "EPF",
  nps: "NPS",
  fd: "Fixed deposits",
  sgb: "Sovereign gold bonds",
  gsec: "G-Sec",
  bond: "Bonds",
  cash: "Cash",
};

export default function NetWorthPage() {
  const { data, isLoading, error } = useNetWorth();

  const breakdown = React.useMemo(() => {
    const entries = Object.entries(data?.breakdown_inr ?? {});
    return entries.sort((a, b) => b[1] - a[1]);
  }, [data]);

  const total = data?.current_inr ?? 0;
  const first = data?.timeline?.[0]?.net_worth_inr;
  const changeSinceStart =
    first && first > 0 ? (total - first) / first : null;

  return (
    <div className="space-y-6">
      <div className="page-header">
        <div className="eyebrow">Wealth // all asset classes</div>
        <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
          Net Worth
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Everything you hold in one number — liquid positions marked to market,
          illiquid and manual assets (PPF/EPF/FD/SGB) held at cost basis.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Kpi
          label="Net worth"
          value={data ? formatINR(total) : "—"}
          hint="marked + cost-basis"
          icon={<Wallet className="h-3.5 w-3.5" />}
          loading={isLoading}
        />
        <Kpi
          label="Asset classes"
          value={data ? String(breakdown.length) : "—"}
          hint="with a balance"
          icon={<Layers className="h-3.5 w-3.5" />}
          loading={isLoading}
        />
        <Kpi
          label="Since series start"
          value={
            changeSinceStart == null
              ? "—"
              : `${changeSinceStart >= 0 ? "+" : ""}${(changeSinceStart * 100).toFixed(1)}%`
          }
          hint="priced book only"
          icon={<TrendingUp className="h-3.5 w-3.5" />}
          loading={isLoading}
        />
      </div>

      {isLoading ? (
        <Skeleton className="h-80 w-full" />
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load net worth: {(error as Error).message}
        </div>
      ) : !data || (breakdown.length === 0 && total === 0) ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={Wallet}
            title="No holdings yet"
            description="Import broker CSVs or add holdings, and your consolidated net worth — across equity, crypto, PPF, FD and more — appears here."
          />
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <section className="border border-border/60 bg-card lg:col-span-7">
            <div className="border-b border-border/40 p-5">
              <div className="eyebrow">Allocation</div>
              <h3 className="mt-1 font-serif text-xl tracking-tight">
                Breakdown by asset class
              </h3>
            </div>
            <div className="space-y-3 p-5">
              {breakdown.map(([cat, value]) => {
                const pct = total > 0 ? value / total : 0;
                return (
                  <div key={cat}>
                    <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                      <span className="font-label text-xs uppercase tracking-wider text-foreground">
                        {CATEGORY_LABELS[cat] ?? cat}
                      </span>
                      <span className="font-mono tabular-nums text-muted-foreground">
                        {formatINR(value)} · {(pct * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden bg-secondary/40">
                      <div
                        className="h-full bg-primary"
                        style={{ width: `${Math.min(100, pct * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="border border-border/60 bg-card lg:col-span-5">
            <div className="border-b border-border/40 p-5">
              <div className="eyebrow">History</div>
              <h3 className="mt-1 font-serif text-xl tracking-tight">
                Net-worth timeline
              </h3>
            </div>
            <NetWorthTimeline points={data.timeline} />
          </section>
        </div>
      )}
    </div>
  );
}

function NetWorthTimeline({
  points,
}: {
  points: { date: string; net_worth_inr: number }[];
}) {
  if (!points.length) {
    return (
      <p className="p-5 text-xs text-muted-foreground">
        No priced history yet — illiquid-only books show a flat cost-basis value.
      </p>
    );
  }
  const values = points.map((p) => p.net_worth_inr);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 100;
  const h = 40;
  const path = points
    .map((p, i) => {
      const x = (i / Math.max(1, points.length - 1)) * w;
      const y = h - ((p.net_worth_inr - min) / span) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const recent = points.slice(-6).reverse();
  return (
    <div className="space-y-4 p-5">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-24 w-full" preserveAspectRatio="none">
        <path d={path} fill="none" stroke="currentColor" strokeWidth={0.8} className="text-primary" />
      </svg>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-border/30">
          {recent.map((p) => (
            <tr key={p.date} className={cn("hover-tile")}>
              <td className="py-1.5 font-mono text-[11px] text-muted-foreground">
                {p.date}
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums">
                {formatINR(p.net_worth_inr)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
