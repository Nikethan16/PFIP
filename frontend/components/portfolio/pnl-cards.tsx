"use client";

import { Card, Metric, Text } from "@tremor/react";

import type { PortfolioSummary } from "@/lib/contracts";
import { formatINR, formatPct } from "@/lib/utils";

interface PnlCardsProps {
  summary: PortfolioSummary | undefined;
  loading?: boolean;
  dayChangeInr?: number;
  dayChangePct?: number;
  sharpe30d?: number;
}

/**
 * KPI strip for the portfolio page.
 *
 * Row (desktop): total | overall P&L | unrealised / realised | drawdown | day change | Sharpe-30d.
 * Mobile: 2-up grid that wraps into rows.
 */
export function PnlCards({
  summary,
  loading,
  dayChangeInr,
  dayChangePct,
  sharpe30d,
}: PnlCardsProps) {
  if (loading || !summary) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="animate-pulse">
            <Text>Loading…</Text>
            <Metric>—</Metric>
          </Card>
        ))}
      </div>
    );
  }

  const overallTone =
    summary.pnl_inr >= 0 ? "text-emerald-600" : "text-red-600";
  const ddTone =
    summary.drawdown_pct <= -10 ? "text-red-600" : "text-amber-600";
  const dayTone =
    (dayChangeInr ?? 0) >= 0 ? "text-emerald-600" : "text-red-600";

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Card>
        <Text>Total value</Text>
        <Metric>{formatINR(summary.total_inr)}</Metric>
      </Card>
      <Card>
        <Text>Overall P&amp;L</Text>
        <Metric className={overallTone}>{formatINR(summary.pnl_inr)}</Metric>
        <Text>{formatPct(summary.pnl_pct)}</Text>
      </Card>
      <Card>
        <Text>Unrealised</Text>
        <Metric>{formatINR(summary.unrealized_pnl_inr)}</Metric>
        <Text>Realised: {formatINR(summary.realized_pnl_inr)}</Text>
      </Card>
      <Card>
        <Text>Drawdown</Text>
        <Metric className={ddTone}>{formatPct(summary.drawdown_pct)}</Metric>
      </Card>
      <Card>
        <Text>Day change</Text>
        <Metric className={dayTone}>
          {dayChangeInr != null ? formatINR(dayChangeInr) : "—"}
        </Metric>
        <Text>
          {dayChangePct != null ? formatPct(dayChangePct) : "—"}
        </Text>
      </Card>
      <Card>
        <Text>Sharpe 30d</Text>
        <Metric
          className={
            (sharpe30d ?? 0) >= 1 ? "text-emerald-600" : "text-amber-600"
          }
        >
          {sharpe30d != null ? sharpe30d.toFixed(2) : "—"}
        </Metric>
      </Card>
    </div>
  );
}
