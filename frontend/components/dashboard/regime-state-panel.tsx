"use client";

/**
 * "Market Regime State" — the one dark charcoal panel in the Sahara dashboard.
 *
 * Built ENTIRELY from real hooks; every bar is labelled with the metric it
 * actually represents (no fabricated "trend vs mean-reversion" splits):
 *
 *   - REGIME CONFIDENCE → useAssetRegime(asset).confidence   (0..1)
 *   - PORTFOLIO VOLATILITY (VaR 95%) → useVarPanel().var_95_pct, shown on a
 *     0..10% display scale (1-day 95% value-at-risk as % of book)
 *   - CONCENTRATION (HHI) → useVarPanel().concentration_hhi   (0..1)
 *
 * The serif-italic one-liner restates the live regime label as prose.
 */

import { useAssetRegime, useVarPanel } from "@/lib/api";
import type { Regime } from "@/lib/contracts";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// Humanised regime label + a short prose read, keyed off the six real regimes
// (+ the backend's neutral "unknown").
const REGIME_COPY: Record<
  Regime | "unknown",
  { label: string; quote: string; blurb: string }
> = {
  bull_trend: {
    label: "Bull Trend",
    quote: "Trending higher.",
    blurb:
      "Momentum is the dominant driver. Trend-following posture favoured over fading strength.",
  },
  bear_trend: {
    label: "Bear Trend",
    quote: "Trending lower.",
    blurb:
      "Downside momentum in control. Rallies are suspect until structure reclaims.",
  },
  sideways: {
    label: "Range-Bound",
    quote: "Coiling sideways.",
    blurb:
      "No directional edge. Mean-reversion at the edges of the range tends to pay over breakouts.",
  },
  high_volatility: {
    label: "High Volatility",
    quote: "Volatile and unstable.",
    blurb:
      "Realised volatility is elevated. Size down — wide stops and headline risk dominate.",
  },
  accumulation: {
    label: "Accumulation",
    quote: "Quietly accumulating.",
    blurb:
      "Basing behaviour after weakness. Demand absorbing supply ahead of a potential turn.",
  },
  distribution: {
    label: "Distribution",
    quote: "Topping out.",
    blurb:
      "Supply overwhelming demand near highs. Strength is being sold into.",
  },
  unknown: {
    label: "Unclassified",
    quote: "Awaiting a read.",
    blurb:
      "The regime classifier hasn't labelled this asset yet. Run the daily HMM flow to populate it.",
  },
};

interface RegimeStatePanelProps {
  /** Asset whose regime headlines the panel (e.g. "BTC-USD"). */
  asset: string;
  /** Friendly asset label for the eyebrow (e.g. "BTC"). */
  assetLabel?: string;
}

export function RegimeStatePanel({ asset, assetLabel }: RegimeStatePanelProps) {
  const { data: regime, isLoading: loadingRegime } = useAssetRegime(asset);
  const { data: risk, isLoading: loadingRisk } = useVarPanel();

  const copy = regime ? REGIME_COPY[regime.regime] : null;

  // Confidence: 0..1 → percent.
  const confidencePct = regime ? Math.round(regime.confidence * 100) : null;

  // Volatility proxy: 1-day 95% VaR as % of book, mapped onto a 0..10% display
  // scale so the bar is legible. Honest label: "Portfolio VaR (95%)".
  const varPct = risk ? Math.abs(risk.var_95_pct) : null;
  const volBarPct =
    varPct != null ? Math.min(100, (varPct / 10) * 100) : null;
  const volState =
    varPct == null
      ? null
      : varPct >= 6
        ? "HIGH"
        : varPct >= 3
          ? "ELEVATED"
          : "CONTAINED";

  // Concentration: HHI is already 0..1 (1 = single-asset book).
  const hhi = risk ? Math.min(1, Math.max(0, risk.concentration_hhi)) : null;
  const hhiPct = hhi != null ? Math.round(hhi * 100) : null;

  const loading = loadingRegime || loadingRisk;

  return (
    <div className="dark flex h-full flex-col bg-[#1b1c1c] p-6 text-foreground">
      <div className="mb-6">
        <h3 className="font-label text-xs uppercase tracking-[0.2em] text-foreground/60">
          Market Regime State
        </h3>
        <div className="mt-2 h-0.5 w-12 bg-primary" />
        {assetLabel ? (
          <div className="mt-2 font-mono text-[11px] text-foreground/50">
            {assetLabel} · {asset}
          </div>
        ) : null}
      </div>

      {loading ? (
        <div className="space-y-6">
          <Skeleton className="h-10 w-full bg-foreground/10" />
          <Skeleton className="h-10 w-full bg-foreground/10" />
          <Skeleton className="h-10 w-full bg-foreground/10" />
        </div>
      ) : (
        <>
          <div className="space-y-6">
            <Bar
              label="Regime Confidence"
              valueLabel={confidencePct != null ? `${confidencePct}%` : "—"}
              pct={confidencePct}
              barClassName="bg-primary"
            />
            <Bar
              label="Portfolio VaR (95%)"
              valueLabel={
                varPct != null
                  ? `${varPct.toFixed(1)}% · ${volState}`
                  : "—"
              }
              pct={volBarPct}
              barClassName={
                varPct != null && varPct >= 6
                  ? "bg-red-500"
                  : varPct != null && varPct >= 3
                    ? "bg-amber-500"
                    : "bg-emerald-500"
              }
            />
            <Bar
              label="Concentration (HHI)"
              valueLabel={hhiPct != null ? `${hhiPct}%` : "—"}
              pct={hhiPct}
              barClassName="bg-foreground/50"
            />
          </div>

          <div className="mt-8 border-t border-foreground/10 pt-6">
            <p className="font-serif text-xl italic leading-snug">
              &ldquo;{copy?.quote ?? "Awaiting a read."}&rdquo;
            </p>
            <p className="mt-3 text-xs leading-relaxed text-foreground/60">
              {copy?.blurb ??
                "Regime data is unavailable. Once the classifier runs, the live read appears here."}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function Bar({
  label,
  valueLabel,
  pct,
  barClassName,
}: {
  label: string;
  valueLabel: string;
  /** 0..100 fill; null renders an empty track. */
  pct: number | null;
  barClassName: string;
}) {
  const width = pct == null ? 0 : Math.min(100, Math.max(0, pct));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-end justify-between font-mono text-[11px] text-foreground/70">
        <span className="font-label uppercase tracking-wider">{label}</span>
        <span className="tabular-nums">{valueLabel}</span>
      </div>
      <div
        className="h-1.5 w-full bg-foreground/10"
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(width)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn("h-full transition-all duration-500", barClassName)}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}
