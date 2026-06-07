"use client";

/**
 * Sahara "Shadow Portfolio" — the model's own paper-traded book.
 *
 * The shadow portfolio is a MEASUREMENT INSTRUMENT, not a trading interface: the
 * engine paper-trades its own signals (with the same risk rules as the live
 * book) so we can measure whether the model has real edge WITHOUT risking
 * capital. This page is advisory/observational — there are NO buy/sell buttons.
 *
 * Data mapping (every value traces to a real hook — no fabrication):
 *   - shadow holdings     ← useShadowHoldings()   (/shadow/holdings)
 *   - shadow value / diff ← useShadowVsActual()    (/shadow/vs-actual)
 *   - "only in shadow"    ← vsActual.only_in_shadow (symbols the model holds
 *                            on paper that your real portfolio does NOT)
 *
 * Position value uses each holding's cost basis (INR), matching how the backend
 * estimates shadow vs actual value — an honest book value, not a live mark.
 */

import * as React from "react";
import Link from "next/link";
import {
  Banknote,
  Copy,
  FlaskConical,
  GitCompareArrows,
  Layers,
  MessageSquareText,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { Kpi } from "@/components/shared/kpi";
import { EmptyState } from "@/components/shared/empty-state";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import { useShadowHoldings, useShadowVsActual } from "@/lib/api";
import type { Holding } from "@/lib/contracts";
import { cn, formatINR, formatIST } from "@/lib/utils";
import { assetClassLabel } from "@/components/portfolio/holding-labels";

export default function ShadowPage() {
  const {
    data: holdings,
    isLoading: loadingHoldings,
    error: holdingsError,
  } = useShadowHoldings();
  const { data: vsActual, isLoading: loadingVs } = useShadowVsActual();

  // Split open vs closed — the open book drives the value + position count.
  const { open, closed } = React.useMemo(() => {
    const all = holdings ?? [];
    return {
      open: all.filter((h) => h.closed_at == null),
      closed: all.filter((h) => h.closed_at != null),
    };
  }, [holdings]);

  const hasAnyData =
    (holdings?.length ?? 0) > 0 || (vsActual?.n_shadow_positions ?? 0) > 0;

  return (
    <div className="space-y-6">
      {/* Header — serif "Shadow Portfolio" + advisory framing. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Paper-traded // measurement, not advice
            <FreshnessBadge sources={["shadow_apply_signals_daily"]} />
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Shadow Portfolio
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            A paper book the engine trades from its own signals — same risk
            rules, no real money — so we can measure the model&apos;s edge before
            trusting it. Observational only: there are no orders here.
          </p>
        </div>
        <Link
          href={"/portfolio" as never}
          className="inline-flex items-center gap-2 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
        >
          <Banknote className="h-3.5 w-3.5" />
          Real portfolio
        </Link>
      </div>

      {/* KPI strip — shadow value / open positions / vs-actual delta. */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Kpi
          label="Shadow value"
          value={vsActual ? formatINR(vsActual.shadow_value_inr) : "—"}
          hint="paper book · cost basis"
          icon={<FlaskConical className="h-3.5 w-3.5" />}
          loading={loadingVs}
          freshness={vsActual ? "fresh" : undefined}
        />
        <Kpi
          label="Open positions"
          value={
            vsActual
              ? String(vsActual.n_shadow_positions)
              : open.length
                ? String(open.length)
                : "—"
          }
          hint={closed.length ? `${closed.length} closed` : "model-selected"}
          icon={<Layers className="h-3.5 w-3.5" />}
          loading={loadingVs || loadingHoldings}
        />
        <Kpi
          label="Only in shadow"
          accent
          value={vsActual ? String(vsActual.only_in_shadow.length) : "—"}
          valueClassName="text-primary"
          hint="not in your real book"
          icon={<GitCompareArrows className="h-3.5 w-3.5" />}
          loading={loadingVs}
        />
      </div>

      {loadingHoldings ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <Skeleton className="h-[24rem] w-full lg:col-span-7" />
          <Skeleton className="h-[24rem] w-full lg:col-span-5" />
        </div>
      ) : holdingsError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load the shadow portfolio: {(holdingsError as Error).message}
        </div>
      ) : !hasAnyData ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={FlaskConical}
            title="No shadow positions yet"
            description="The shadow book fills as the engine applies its own calibrated signals on paper. Once the shadow flow runs and signals clear the risk gate, the model's paper positions appear here."
          />
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Holdings book (open + closed) */}
          <section className="flex min-h-[24rem] flex-col border border-border/60 bg-card lg:col-span-7">
            <div className="border-b border-border/40 p-5">
              <div className="eyebrow">Paper holdings</div>
              <h3 className="mt-1 font-serif text-xl tracking-tight">
                Model&apos;s book · {open.length} open
              </h3>
            </div>
            <ShadowHoldingsTable open={open} closed={closed} />
          </section>

          {/* vs-actual comparison */}
          <div className="lg:col-span-5">
            <VsActualPanel data={vsActual} loading={loadingVs} />
          </div>
        </div>
      )}
    </div>
  );
}

// --- Holdings table ----------------------------------------------------------

/** Cost-basis book value for a paper holding (matches backend estimate). */
function bookValue(h: Holding): number {
  return h.cost_basis_inr ?? 0;
}

function ShadowHoldingsTable({
  open,
  closed,
}: {
  open: Holding[];
  closed: Holding[];
}) {
  return (
    <div className="flex-1 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/40 bg-secondary/30 text-left font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-5 py-2.5 font-medium">Symbol</th>
            <th className="px-3 py-2.5 font-medium">Class</th>
            <th className="px-3 py-2.5 text-right font-medium">Qty</th>
            <th className="px-3 py-2.5 text-right font-medium">Value</th>
            <th className="px-5 py-2.5 text-right font-medium">Opened</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {open.map((h) => (
            <ShadowRow key={h.id} h={h} />
          ))}
          {closed.length ? (
            <>
              <tr>
                <td
                  colSpan={5}
                  className="bg-secondary/20 px-5 py-1.5 font-label text-[10px] uppercase tracking-wider text-muted-foreground"
                >
                  Closed · {closed.length}
                </td>
              </tr>
              {closed.map((h) => (
                <ShadowRow key={h.id} h={h} closed />
              ))}
            </>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function ShadowRow({ h, closed }: { h: Holding; closed?: boolean }) {
  return (
    <tr className={cn("hover-tile", closed && "opacity-55")}>
      <td className="px-5 py-2.5">
        <span className="font-mono text-sm font-semibold">
          {h.symbol ?? h.isin ?? "—"}
        </span>
      </td>
      <td className="px-3 py-2.5">
        <span className="font-label text-[11px] uppercase tracking-wider text-muted-foreground">
          {assetClassLabel(h.category)}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">
        {h.qty.toLocaleString("en-IN", { maximumFractionDigits: 4 })}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">
        {formatINR(bookValue(h))}
      </td>
      <td className="px-5 py-2.5 text-right font-mono text-[11px] text-muted-foreground tabular-nums">
        {formatIST(h.acquired_at, "dd MMM yyyy")}
      </td>
    </tr>
  );
}

// --- vs-actual comparison ----------------------------------------------------

function VsActualPanel({
  data,
  loading,
}: {
  data: import("@/lib/api").ShadowVsActual | undefined;
  loading: boolean;
}) {
  return (
    <section className="flex h-full flex-col border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow flex items-center gap-1.5">
          <GitCompareArrows className="h-3.5 w-3.5" />
          Shadow vs your portfolio
        </div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">
          What the model holds that you don&apos;t
        </h3>
      </div>

      <div className="flex-1 space-y-5 p-5">
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : !data ? (
          <p className="text-xs text-muted-foreground">
            Comparison unavailable.
          </p>
        ) : (
          <>
            {/* Value comparison */}
            <div className="grid grid-cols-2 gap-3">
              <div className="border border-border/50 bg-secondary/40 p-3">
                <div className="eyebrow">Shadow value</div>
                <div className="mt-0.5 font-mono text-base font-semibold tabular-nums">
                  {formatINR(data.shadow_value_inr)}
                </div>
              </div>
              <div className="border border-border/50 bg-secondary/40 p-3">
                <div className="eyebrow">Your (real) value</div>
                <div className="mt-0.5 font-mono text-base font-semibold tabular-nums">
                  {formatINR(data.actual_value_inr)}
                </div>
              </div>
            </div>

            {/* Symbol-set diff */}
            <SymbolGroup
              title="Only in shadow"
              hint="model holds on paper; you don't"
              tone="primary"
              symbols={data.only_in_shadow}
            />
            <SymbolGroup
              title="In both"
              hint="model agrees with your book"
              tone="emerald"
              symbols={data.in_both}
            />
            <SymbolGroup
              title="Only in your portfolio"
              hint="you hold; the model hasn't"
              tone="muted"
              symbols={data.only_in_actual}
            />
          </>
        )}
      </div>

      <div className="border-t border-border/40 p-5">
        <Link
          href={"/chat" as never}
          className="inline-flex items-center gap-1.5 font-label text-[11px] uppercase tracking-wider text-primary hover:underline"
        >
          <MessageSquareText className="h-3.5 w-3.5" />
          Ask why the model holds these
        </Link>
      </div>
    </section>
  );
}

function SymbolGroup({
  title,
  hint,
  symbols,
  tone,
}: {
  title: string;
  hint: string;
  symbols: string[];
  tone: "primary" | "emerald" | "muted";
}) {
  const chip =
    tone === "primary"
      ? "border-primary/40 bg-primary/10 text-primary"
      : tone === "emerald"
        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
        : "border-border/60 bg-secondary/40 text-muted-foreground";
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="font-label text-[11px] uppercase tracking-wider text-foreground">
          {title}
          <span className="ml-2 font-mono text-[10px] text-muted-foreground tabular-nums">
            {symbols.length}
          </span>
        </span>
        <span className="text-[10px] text-muted-foreground">{hint}</span>
      </div>
      {symbols.length ? (
        <div className="flex flex-wrap gap-1.5">
          {symbols.map((s) => (
            <span
              key={s}
              className={cn(
                "inline-flex items-center gap-1 border px-2 py-0.5 font-mono text-[11px]",
                chip,
              )}
            >
              {tone === "primary" ? (
                <Copy className="h-2.5 w-2.5" aria-hidden />
              ) : null}
              {s}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">—</p>
      )}
    </div>
  );
}
