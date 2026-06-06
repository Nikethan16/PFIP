"use client";

import * as React from "react";
import Link from "next/link";
import { Download, MessageSquareText, Banknote, TrendingUp, ShieldAlert } from "lucide-react";

import { HoldingsTable, type HoldingMetrics } from "@/components/portfolio/holdings-table";
import { DeepDivePanel } from "@/components/portfolio/deep-dive-panel";
import { CorrelationMatrix } from "@/components/portfolio/correlation-matrix";
import { VarPanel } from "@/components/portfolio/var-panel";
import { MacroShockCard } from "@/components/portfolio/macro-shock-card";
import { MarkingBadge } from "@/components/portfolio/marking-badge";
import { PostMortemDialog } from "@/components/journal/post-mortem-dialog";
import { Kpi } from "@/components/shared/kpi";
import { EmptyState } from "@/components/shared/empty-state";
import { StaleBadge } from "@/components/shared/stale-badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useClosePosition,
  useHoldings,
  useMarking,
  usePortfolioSummary,
  useVarPanel,
} from "@/lib/api";
import type { Holding } from "@/lib/contracts";
import { toast } from "@/components/ui/toast";
import { formatINR, formatPct } from "@/lib/utils";
import { assetClassLabel, holdingDisplayName } from "@/components/portfolio/holding-labels";

export default function PortfolioPage() {
  const { data: holdings, isLoading: loadingHoldings, error: holdingsError } =
    useHoldings();
  const { data: summary, isLoading: loadingSummary } = usePortfolioSummary();
  const { data: risk } = useVarPanel();
  const { data: marking } = useMarking();
  const closePosition = useClosePosition();

  // Selected holding id → drives the deep-dive panel + row stripe.
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  // Holding whose close is in flight.
  const [closingHoldingId, setClosingHoldingId] = React.useState<string | null>(
    null,
  );
  // Journal entry id of the auto-created post-mortem stub; opens the dialog.
  const [postMortemEntryId, setPostMortemEntryId] = React.useState<
    string | null
  >(null);

  // ---------------------------------------------------------------------------
  // Live mark-to-market: marking.mark_prices_inr is a per-UNIT INR price keyed
  // by symbol. We derive each row's price/avg-cost/value/P&L from it, falling
  // back to cost basis when a holding is unmarked (the marking endpoint says
  // which). Every number here traces to a real hook — no fabrication.
  // ---------------------------------------------------------------------------
  const metrics = React.useMemo(() => {
    const map = new Map<string, HoldingMetrics>();
    const marks = marking?.mark_prices_inr ?? {};
    for (const h of holdings ?? []) {
      const qty = h.qty;
      const avgCostInr = qty ? h.cost_basis_inr / qty : null;
      const markRaw = h.symbol ? marks[h.symbol] : undefined;
      const markPerUnit = markRaw != null ? Number(markRaw) : null;
      const marked = markPerUnit != null && Number.isFinite(markPerUnit);

      const pricePerUnitInr = marked ? markPerUnit : avgCostInr;
      const marketValueInr = marked
        ? markPerUnit * qty
        : h.cost_basis_inr;
      const pnlInr = marked ? markPerUnit * qty - h.cost_basis_inr : null;
      const pnlPct =
        marked && h.cost_basis_inr
          ? (pnlInr! / h.cost_basis_inr) * 100
          : null;

      map.set(h.id, {
        pricePerUnitInr,
        avgCostInr,
        marketValueInr,
        pnlInr,
        pnlPct,
        marked,
      });
    }
    return map;
  }, [holdings, marking]);

  // Auto-select the first holding once they load so the deep-dive isn't empty.
  React.useEffect(() => {
    if (selectedId == null && holdings && holdings.length > 0) {
      setSelectedId(holdings[0]!.id);
    }
  }, [holdings, selectedId]);

  const selectedHolding =
    (holdings ?? []).find((h) => h.id === selectedId) ?? null;

  const handleClosePosition = async (h: Holding) => {
    if (!h.symbol) {
      toast.error("Holding has no symbol — open the journal to link it first.");
      return;
    }
    // Exit at live market value when we have one, else cost basis. The user
    // refines realised P&L in the post-mortem dialog.
    const m = metrics.get(h.id);
    const exitPriceInr = m?.marketValueInr ?? h.cost_basis_inr;
    setClosingHoldingId(h.id);
    try {
      const result = await closePosition.mutateAsync({
        holdingId: h.id,
        exit_price_inr: exitPriceInr,
      });
      setPostMortemEntryId(result.journal_entry_id);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setClosingHoldingId(null);
    }
  };

  const handleExportCsv = React.useCallback(() => {
    const rows = holdings ?? [];
    if (!rows.length) {
      toast.error("No holdings to export.");
      return;
    }
    const header = [
      "symbol",
      "name",
      "asset_class",
      "qty",
      "avg_cost_inr",
      "price_inr",
      "market_value_inr",
      "unrealized_pnl_inr",
      "unrealized_pnl_pct",
      "marked",
    ];
    const escape = (v: string | number | null | undefined) => {
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const body = rows.map((h) => {
      const m = metrics.get(h.id);
      return [
        h.symbol ?? h.isin ?? "",
        holdingDisplayName(h),
        assetClassLabel(h.category),
        h.qty,
        m?.avgCostInr ?? "",
        m?.pricePerUnitInr ?? "",
        m?.marketValueInr ?? "",
        m?.pnlInr ?? "",
        m?.pnlPct ?? "",
        m?.marked ? "live" : "cost_basis",
      ]
        .map(escape)
        .join(",");
    });
    const csv = [header.join(","), ...body].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pfip-holdings-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [holdings, metrics]);

  // Day P&L tone for the KPI strip.
  const dayPositive = (risk?.day_change_inr ?? 0) >= 0;
  const drawdownPct =
    summary != null ? -Math.abs(summary.drawdown) * 100 : null;

  return (
    <div className="space-y-6">
      {/* Header — serif "Global Holdings" + subtitle + actions. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow">Aggregated // mark-to-market</div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Global Holdings
          </h1>
          <div className="mt-1 flex items-center gap-3">
            <MarkingBadge marking={marking} />
            {/* Freshness comes from /portfolio/marking.as_of; /summary carries none. */}
            {marking?.as_of ? <StaleBadge updatedAt={marking.as_of} /> : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleExportCsv}
            className="inline-flex items-center gap-2 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
          >
            <Download className="h-3.5 w-3.5" />
            Export CSV
          </button>
          {/* Advisory-only: "Rebalance" opens the agent rather than placing trades. */}
          <Link
            href={"/chat" as never}
            className="inline-flex items-center gap-2 bg-primary px-4 py-2 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
          >
            <MessageSquareText className="h-3.5 w-3.5" />
            Rebalance
          </Link>
        </div>
      </div>

      {/* KPI strip — net worth / day P&L / drawdown / Sharpe (real hooks). */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Kpi
          label="Net worth"
          value={summary ? formatINR(summary.total_inr) : "—"}
          deltaPct={summary?.pnl_pct ?? null}
          hint={summary ? "vs cost basis" : null}
          icon={<Banknote className="h-3.5 w-3.5" />}
          loading={loadingSummary}
          freshness={summary ? "fresh" : undefined}
        />
        <Kpi
          label="P&L today"
          value={risk ? formatINR(risk.day_change_inr) : "—"}
          valueClassName={
            risk == null
              ? undefined
              : dayPositive
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-red-700 dark:text-red-400"
          }
          deltaPct={risk?.day_change_pct ?? null}
          icon={<TrendingUp className="h-3.5 w-3.5" />}
          loading={loadingSummary}
          freshness={risk ? "fresh" : undefined}
        />
        <Kpi
          label="Max drawdown"
          value={drawdownPct != null ? formatPct(drawdownPct) : "—"}
          tone={
            drawdownPct == null
              ? "neutral"
              : drawdownPct <= -10
                ? "down"
                : "neutral"
          }
          hint={summary ? "peak-to-current" : null}
          icon={<ShieldAlert className="h-3.5 w-3.5" />}
          loading={loadingSummary}
        />
        <Kpi
          label="Sharpe · 30d"
          accent
          value={risk ? risk.sharpe_30d.toFixed(2) : "—"}
          tone="neutral"
          valueClassName="text-primary"
          hint={risk ? (risk.sharpe_30d >= 1 ? "healthy" : "watch") : null}
          icon={<TrendingUp className="h-3.5 w-3.5" />}
          loading={loadingSummary}
        />
      </div>

      {/* Split pane: holdings table (≈2/3) + deep-dive analytics (≈1/3). */}
      {loadingHoldings ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <Skeleton className="h-[28rem] w-full lg:col-span-8" />
          <Skeleton className="h-[28rem] w-full lg:col-span-4" />
        </div>
      ) : holdingsError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load holdings: {(holdingsError as Error).message}
        </div>
      ) : !holdings?.length ? (
        <section className="border border-border/60 bg-card p-6">
          <EmptyState
            title="Portfolio empty"
            description="Import broker CSVs (Zerodha / INDmoney / WazirX / CoinDCX) on the Tax page to start tracking mark-to-market, P&L and risk."
            action={{ label: "Go to tax imports", href: "/tax" }}
          />
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <section className="flex min-h-[28rem] flex-col border border-border/60 bg-card lg:col-span-8">
            <div className="border-b border-border/40 p-4">
              <div className="eyebrow">Holdings ledger</div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Live-priced where available · click a row to deep-dive.
              </p>
            </div>
            <HoldingsTable
              holdings={holdings}
              metrics={metrics}
              selectedId={selectedId}
              onSelect={(h) => setSelectedId(h.id)}
            />
          </section>
          <div className="lg:col-span-4">
            <DeepDivePanel
              holding={selectedHolding}
              onClosePosition={handleClosePosition}
              closing={
                selectedHolding != null &&
                closingHoldingId === selectedHolding.id
              }
            />
          </div>
        </div>
      )}

      {/* Risk + macro shock + full correlation matrix (preserved analytics). */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <VarPanel />
        </div>
        <MacroShockCard />
      </div>

      <section className="border border-border/60 bg-card">
        <div className="border-b border-border/40 p-5">
          <div className="eyebrow">Correlation matrix</div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Pairwise correlation · daily returns
          </h3>
        </div>
        <div className="p-5">
          <CorrelationMatrix />
        </div>
      </section>

      {/*
        Close-position post-mortem. Closing a holding creates a linked
        post-mortem journal stub server-side (audit H4); we open the dialog
        with that JOURNAL entry id so the save targets the journal, not the
        holding.
      */}
      <PostMortemDialog
        open={postMortemEntryId !== null}
        entryId={postMortemEntryId}
        onOpenChange={(next) => !next && setPostMortemEntryId(null)}
      />
    </div>
  );
}
