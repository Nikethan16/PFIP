"use client";

import * as React from "react";
import { Card, DonutChart, Title } from "@tremor/react";

import {
  Card as ShadCard,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PnlCards } from "@/components/portfolio/pnl-cards";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { CorrelationMatrix } from "@/components/portfolio/correlation-matrix";
import { VarPanel } from "@/components/portfolio/var-panel";
import { MacroShockCard } from "@/components/portfolio/macro-shock-card";
import { PostMortemDialog } from "@/components/journal/post-mortem-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { StaleBadge } from "@/components/shared/stale-badge";
import { PageHeader } from "@/components/shared/page-header";
import {
  useClosePosition,
  useHoldings,
  useMarking,
  usePortfolioSummary,
  useVarPanel,
} from "@/lib/api";
import type { Holding, HoldingCategory } from "@/lib/contracts";
import { toast } from "@/components/ui/toast";
import { formatINR, formatIST } from "@/lib/utils";
import { MarkingBadge } from "@/components/portfolio/marking-badge";

export default function PortfolioPage() {
  const { data: holdings, isLoading: loadingHoldings, error: holdingsError } =
    useHoldings();
  const { data: summary, isLoading: loadingSummary } = usePortfolioSummary();
  const { data: risk } = useVarPanel();
  const { data: marking } = useMarking();
  const closePosition = useClosePosition();

  // Holding whose close is in flight (drives the row's "Closing…" state).
  const [closingHoldingId, setClosingHoldingId] = React.useState<string | null>(
    null,
  );
  // Journal entry id of the auto-created post-mortem stub; opens the dialog.
  const [postMortemEntryId, setPostMortemEntryId] = React.useState<
    string | null
  >(null);

  const handleClosePosition = async (h: Holding) => {
    if (!h.symbol) {
      toast.error("Holding has no symbol — open the journal to link it first.");
      return;
    }
    // Exit at the live market value when we have one, else cost basis. The
    // user refines the realised P&L in the post-mortem dialog.
    const exitPriceInr = h.market_value_inr ?? h.cost_basis_inr;
    setClosingHoldingId(h.id);
    try {
      const result = await closePosition.mutateAsync({
        holdingId: h.id,
        exit_price_inr: exitPriceInr,
      });
      // Open the post-mortem dialog with the JOURNAL entry id (audit H4) —
      // NOT the holding id.
      setPostMortemEntryId(result.journal_entry_id);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setClosingHoldingId(null);
    }
  };

  const exposure = summary
    ? (
        Object.entries(summary.exposure_by_category) as Array<
          [HoldingCategory, number]
        >
      ).map(([category, value]) => ({ category, value }))
    : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio"
        description={
          summary ? (
            <span className="flex items-baseline gap-3">
              <span className="font-num text-base font-semibold text-foreground">
                {formatINR(summary.total_inr)}
              </span>
              <span className="text-muted-foreground">
                across equities, ETFs, MFs, PPF, EPF, NPS, FDs, gold, bonds,
                and crypto.
              </span>
            </span>
          ) : (
            "Unified view across equities, ETFs, MFs, PPF, EPF, NPS, FDs, gold, bonds, and crypto."
          )
        }
        actions={
          <span className="flex items-center gap-3">
            <MarkingBadge marking={marking} />
            {summary ? <StaleBadge updatedAt={summary.updated_at} /> : null}
          </span>
        }
      />

      <PnlCards
        summary={summary}
        loading={loadingSummary}
        dayChangeInr={risk?.day_change_inr}
        dayChangePct={risk?.day_change_pct}
        sharpe30d={risk?.sharpe_30d}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <Title>Exposure by category</Title>
          {loadingSummary ? (
            <Skeleton className="mt-4 h-56 w-full" />
          ) : exposure.length ? (
            <DonutChart
              className="mt-4 h-56"
              data={exposure}
              category="value"
              index="category"
              valueFormatter={(v) =>
                new Intl.NumberFormat("en-IN", {
                  style: "currency",
                  currency: "INR",
                  maximumFractionDigits: 0,
                }).format(v)
              }
              colors={[
                "blue",
                "emerald",
                "amber",
                "rose",
                "violet",
                "cyan",
                "orange",
                "lime",
                "pink",
                "teal",
                "slate",
                "indigo",
                "red",
              ]}
            />
          ) : (
            <EmptyState
              title="No exposure data"
              description="Start by importing broker CSVs on the Tax page."
              action={{ label: "Import CSVs", href: "/tax" }}
              className="mt-4"
            />
          )}
        </Card>

        <ShadCard className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Correlation matrix</CardTitle>
            <CardDescription>
              Pairwise correlation of daily returns across top holdings.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CorrelationMatrix />
          </CardContent>
        </ShadCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <VarPanel />
        </div>
        <MacroShockCard />
      </div>

      <div>
        <h2 className="mb-3 text-lg font-semibold">Holdings</h2>
        {loadingHoldings ? (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : holdingsError ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
            Couldn&apos;t load holdings: {(holdingsError as Error).message}
          </div>
        ) : (
          <HoldingsTable
            holdings={holdings ?? []}
            onClosePosition={handleClosePosition}
            closingHoldingId={closingHoldingId}
          />
        )}
      </div>

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
