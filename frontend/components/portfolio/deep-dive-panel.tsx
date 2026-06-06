"use client";

/**
 * Sahara "Deep Dive Analytics" panel — the right rail of the Portfolio page.
 *
 * Mirrors the mockup's split-pane right column for the SELECTED holding, built
 * ENTIRELY from real hooks (no fabricated metrics):
 *
 *   - DAILY CHANGE %  → last two closes from useCandles(symbol) (~90d, 1d)
 *   - VOLATILITY      → useAssetFeatures(symbol).features.volatility_30d
 *                       (labelled honestly as 30-day realised vol; the gauge is
 *                        a display mapping onto a 0..100% annualised-ish scale)
 *   - PERFORMANCE HISTORY (90D) → useCandles(symbol) rendered via CandleChart
 *   - CORRELATION MATRIX → the selected symbol's row from useCorrelationMatrix
 *
 * IMPORTANT: advisory-only product. The mockup's "EXECUTE ORDER" is replaced
 * with non-execution actions — "Pre-trade check" (the journal pre-trade gate)
 * and "Ask the agent" (→ /chat) — plus the existing close-position action that
 * opens a post-mortem. Nothing here implies order placement.
 */

import * as React from "react";
import Link from "next/link";
import {
  ClipboardCheck,
  MessageSquareText,
  Info,
  XCircle,
} from "lucide-react";

import { CandleChart } from "@/components/charts/candle-chart";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import {
  useAssetFeatures,
  useCandles,
  useCorrelationMatrix,
} from "@/lib/api";
import type { Holding } from "@/lib/contracts";
import { cn, formatPct } from "@/lib/utils";
import { holdingDisplayName } from "./holding-labels";

interface DeepDivePanelProps {
  /** The selected holding, or null when nothing is selected. */
  holding: Holding | null;
  /** Close-position handler (opens the post-mortem flow). */
  onClosePosition?: (holding: Holding) => void;
  /** True while THIS holding's close is in flight. */
  closing?: boolean;
}

export function DeepDivePanel({
  holding,
  onClosePosition,
  closing,
}: DeepDivePanelProps) {
  if (!holding) {
    return (
      <aside className="flex h-full flex-col border border-border/60 bg-secondary/30">
        <PanelChrome symbol="—" name="No holding selected" change={null} />
        <div className="flex flex-1 items-center justify-center p-8">
          <EmptyState
            icon={Info}
            title="Select a holding"
            description="Pick a row from the holdings table to see its volatility, 90-day performance and correlations."
          />
        </div>
      </aside>
    );
  }

  return <DeepDiveBody holding={holding} onClosePosition={onClosePosition} closing={closing} />;
}

function DeepDiveBody({
  holding,
  onClosePosition,
  closing,
}: {
  holding: Holding;
  onClosePosition?: (holding: Holding) => void;
  closing?: boolean;
}) {
  const symbol = holding.symbol ?? holding.isin ?? "—";
  const hasSymbol = Boolean(holding.symbol);

  // ~90 days of daily candles for the performance chart + daily change.
  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 90);
    return d.toISOString();
  }, []);
  const candlesQ = useCandles({
    symbol: hasSymbol ? (holding.symbol as string) : "__none__",
    timeframe: "1d",
    since,
  });
  const featuresQ = useAssetFeatures(hasSymbol ? (holding.symbol as string) : "__none__");
  const corrQ = useCorrelationMatrix();

  const candles = candlesQ.data ?? [];
  const lastClose = candles[candles.length - 1]?.close;
  const prevClose = candles[candles.length - 2]?.close;
  const dailyChange =
    lastClose != null && prevClose
      ? ((lastClose - prevClose) / prevClose) * 100
      : null;

  // 30-day realised volatility from the features endpoint. Stored as a daily
  // stdev of log-returns (a small fraction, e.g. 0.03). Render it as a percent
  // and map onto a 0..100 gauge where ~8%/day daily-vol pins the bar (a very
  // hot asset). Honest label: "Volatility (30d realised)".
  const vol30 = featuresQ.data?.features.volatility_30d ?? null;
  const volPct = vol30 != null ? vol30 * 100 : null;
  const volGauge =
    volPct != null ? Math.min(100, Math.max(0, (volPct / 8) * 100)) : null;
  const volBand =
    volPct == null
      ? null
      : volPct >= 5
        ? "Speculative"
        : volPct >= 2.5
          ? "Elevated"
          : "Stable";

  return (
    <aside className="flex h-full flex-col border border-border/60 bg-secondary/30">
      <PanelChrome
        symbol={symbol}
        name={holdingDisplayName(holding)}
        change={dailyChange}
      />

      <div className="flex-1 space-y-5 overflow-y-auto p-5">
        {/* Volatility gauge */}
        <section className="border border-border/50 bg-card p-5">
          <div className="eyebrow mb-4 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              Volatility · 30d realised
              <FreshnessBadge sources={["features_compute_daily"]} />
            </span>
          </div>
          {featuresQ.isLoading ? (
            <Skeleton className="h-10 w-full" />
          ) : volPct == null ? (
            <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
              No feature row yet. Run the daily compute flow for {symbol}.
            </div>
          ) : (
            <>
              <div className="relative mb-3 h-3 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="absolute inset-y-0 left-0 bg-primary transition-all duration-500"
                  style={{ width: `${volGauge ?? 0}%` }}
                  role="progressbar"
                  aria-label="30-day realised volatility"
                  aria-valuenow={Math.round(volGauge ?? 0)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
              <div className="flex items-center justify-between font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                <span>Stable</span>
                <span className="font-mono font-semibold text-foreground tabular-nums">
                  {volPct.toFixed(2)}% / day · {volBand}
                </span>
                <span>Speculative</span>
              </div>
            </>
          )}
        </section>

        {/* Performance history (90D) */}
        <section className="border border-border/50 bg-card p-5">
          <h4 className="eyebrow mb-3">Performance history · 90d</h4>
          {!hasSymbol ? (
            <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
              This holding has no market symbol to chart.
            </div>
          ) : candlesQ.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : candlesQ.error ? (
            <div className="border border-destructive/40 bg-destructive/5 p-3 text-center text-[11px] text-destructive">
              Couldn&apos;t load candles.
            </div>
          ) : !candles.length ? (
            <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
              No price history for {symbol} yet.
            </div>
          ) : (
            <CandleChart data={candles} height={140} />
          )}
        </section>

        {/* Correlation matrix (selected symbol's row) */}
        <section className="border border-border/50 bg-card p-5">
          <h4 className="eyebrow mb-3">Correlation matrix</h4>
          <CorrelationRow
            symbol={holding.symbol ?? null}
            data={corrQ.data}
            loading={corrQ.isLoading}
          />
        </section>
      </div>

      {/* Advisory action footer — replaces the mockup's "EXECUTE ORDER". */}
      <div className="space-y-2 border-t border-border/40 bg-secondary/50 p-4">
        <div className="flex gap-2">
          <Link
            href={"/journal?new=1" as never}
            className="flex flex-1 items-center justify-center gap-2 bg-primary px-4 py-3 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
          >
            <ClipboardCheck className="h-4 w-4" />
            Pre-trade check
          </Link>
          <Link
            href={"/chat" as never}
            className="flex flex-1 items-center justify-center gap-2 border border-border px-4 py-3 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
          >
            <MessageSquareText className="h-4 w-4" />
            Ask the agent
          </Link>
        </div>
        {onClosePosition && !holding.closed_at ? (
          <button
            type="button"
            disabled={closing}
            onClick={() => onClosePosition(holding)}
            title="Close this position and start its post-mortem"
            className="flex w-full items-center justify-center gap-2 border border-border/60 px-4 py-2.5 font-label text-[11px] uppercase tracking-wider text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive disabled:opacity-60"
          >
            <XCircle className="h-3.5 w-3.5" />
            {closing ? "Closing position…" : "Close position · post-mortem"}
          </button>
        ) : holding.closed_at ? (
          <div className="border border-border/40 px-4 py-2.5 text-center font-label text-[11px] uppercase tracking-wider text-muted-foreground">
            Position closed
          </div>
        ) : null}
      </div>
    </aside>
  );
}

/** Shared header: eyebrow + serif symbol + company name + DAILY CHANGE %. */
function PanelChrome({
  symbol,
  name,
  change,
}: {
  symbol: string;
  name: string;
  change: number | null;
}) {
  const positive = (change ?? 0) >= 0;
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border/40 bg-card p-5">
      <div className="min-w-0">
        <span className="eyebrow inline-block bg-primary/10 px-2 py-0.5 text-primary">
          Deep dive analytics
        </span>
        <h3 className="mt-2 truncate font-serif text-4xl leading-none tracking-tight">
          {symbol}
        </h3>
        <p className="mt-1 truncate text-sm text-muted-foreground">{name}</p>
      </div>
      <div className="shrink-0 text-right">
        <div className="eyebrow">Daily change</div>
        <div
          className={cn(
            "mt-1 font-mono text-2xl font-bold tabular-nums",
            change == null
              ? "text-muted-foreground"
              : positive
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-red-700 dark:text-red-400",
          )}
        >
          {change != null ? formatPct(change) : "—"}
        </div>
      </div>
    </div>
  );
}

/**
 * Mini correlation grid: the selected symbol's row against every other holding
 * in the matrix, coloured by magnitude (amber for strong, faint for weak).
 */
function CorrelationRow({
  symbol,
  data,
  loading,
}: {
  symbol: string | null;
  data: ReturnType<typeof useCorrelationMatrix>["data"];
  loading: boolean;
}) {
  if (loading) return <Skeleton className="h-20 w-full" />;
  if (!data || !data.symbols.length) {
    return (
      <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
        Add at least 2 priced holdings to see correlations.
      </div>
    );
  }

  const idx = symbol ? data.symbols.indexOf(symbol) : -1;
  // Peers = every other symbol; value = corr(selected, peer). When the selected
  // symbol isn't in the matrix, fall back to showing the bare symbol list.
  const cells = data.symbols.map((s, j) => ({
    sym: s,
    self: idx >= 0 && j === idx,
    value: idx >= 0 ? (data.matrix[idx]?.[j] ?? null) : null,
  }));

  return (
    <div>
      <div className="grid grid-cols-4 gap-2">
        {cells.slice(0, 8).map((c) => (
          <div
            key={c.sym}
            className={cn(
              "flex aspect-square flex-col items-center justify-center gap-0.5 border border-border/40 p-1 text-center",
            )}
            style={
              c.self
                ? undefined
                : c.value != null
                  ? { backgroundColor: corrBg(c.value) }
                  : undefined
            }
            title={
              c.value != null && symbol
                ? `${symbol} vs ${c.sym}: ${c.value.toFixed(2)}`
                : c.sym
            }
          >
            <span
              className={cn(
                "font-label text-[10px] uppercase leading-tight",
                c.self ? "text-muted-foreground/50" : "text-foreground/80",
              )}
            >
              {c.sym}
            </span>
            {!c.self && c.value != null ? (
              <span className="font-mono text-[10px] tabular-nums">
                {c.value.toFixed(2)}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      <p className="mt-3 text-center text-[11px] italic text-muted-foreground">
        {idx >= 0
          ? `Trailing ${data.window_days}d · close-to-close returns.`
          : `${symbol ?? "This holding"} is not in the correlation set yet.`}
      </p>
    </div>
  );
}

/** Amber tint scaled by |corr| (0 → faint, 1 → solid amber). */
function corrBg(v: number): string {
  const a = Math.min(1, Math.abs(v));
  // hsl amber ≈ 25deg; lighten as correlation weakens.
  return `hsla(25, 80%, 55%, ${(0.12 + a * 0.4).toFixed(3)})`;
}
