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
import { PostMortemDialog } from "@/components/journal/post-mortem-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { StaleBadge } from "@/components/shared/stale-badge";
import {
  useHoldings,
  usePortfolioSummary,
  useVarPanel,
} from "@/lib/api";
import type { Holding, HoldingCategory } from "@/lib/contracts";
import { toast } from "@/components/ui/toast";

export default function PortfolioPage() {
  const { data: holdings, isLoading: loadingHoldings, error: holdingsError } =
    useHoldings();
  const { data: summary, isLoading: loadingSummary } = usePortfolioSummary();
  const { data: risk } = useVarPanel();

  const [closingHolding, setClosingHolding] =
    React.useState<Holding | null>(null);

  const exposure = summary
    ? (
        Object.entries(summary.exposure_by_category) as Array<
          [HoldingCategory, number]
        >
      ).map(([category, value]) => ({ category, value }))
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Portfolio</h1>
          <p className="text-sm text-muted-foreground">
            Unified view across equities, ETFs, MFs, PPF, EPF, NPS, FDs, gold,
            bonds, and crypto.
          </p>
        </div>
        {summary ? <StaleBadge updatedAt={summary.updated_at} /> : null}
      </div>

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

      <VarPanel />

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
            onClosePosition={(h) => {
              // We scope the close dialog to holdings that have a journal entry
              // via symbol match. If not, a soft toast — the user needs to
              // record the pre-trade first.
              if (!h.symbol) {
                toast.error("Holding has no symbol — open the journal to link it first.");
                return;
              }
              setClosingHolding(h);
            }}
          />
        )}
      </div>

      {/*
        Close-position post-mortem. We reuse the agent-drafted dialog; for
        holdings that map to a journal entry we pass the entry_id. If the
        backend hasn't linked them, we just let the user know.
        TODO(user): wire backend `/portfolio/holdings/{id}/journal-entry` so we
        can resolve the journal id from a holding without a manual lookup.
      */}
      <PostMortemDialog
        open={closingHolding !== null}
        entryId={closingHolding ? closingHolding.id : null}
        onOpenChange={(next) => !next && setClosingHolding(null)}
      />
    </div>
  );
}
