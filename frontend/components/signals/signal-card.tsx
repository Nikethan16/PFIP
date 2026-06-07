"use client";

/**
 * Sahara "Alert Stream" signal card — the rich, expandable row of the Signals
 * page, mirroring the refined-palette mockup.
 *
 * Built ENTIRELY from the real `Signal` contract + live hooks. Layout follows
 * the mockup's two-column split:
 *
 *   Left rail (always visible)
 *     - asset + category sub-label + direction-coloured icon tile
 *     - DIRECTION badge        ← signal.direction
 *     - CONFIDENCE % + bar     ← signal.confidence (0..100 int)
 *     - REFERENCE CLOSE        ← latest close from useCandles(asset)
 *         (the Signal contract carries NO entry/target/price field, so this is
 *          an honest "latest close" reference, NOT an order entry. Renders "—"
 *          until candles exist.)
 *
 *   Right column
 *     - reasoning tag          ← humanised regime + horizon
 *     - chevron to expand/collapse
 *     - FEATURE CONTRIBUTION   ← signal.drivers (signed green/red bars)
 *     - NARRATIVE CONTEXT      ← signal.counter_arguments as prose (the
 *         model's against-case), in a bordered box
 *     - MARKET INTELLIGENCE CLUSTER ← useAssetNews(asset) headlines
 *
 * ADVISORY-ONLY: there is no execute affordance. The footer links to the
 * journal (pre-trade gate / existing entry) and to the agent (→ /chat).
 */

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bitcoin,
  ChevronDown,
  CircleDollarSign,
  Clock,
  FlaskConical,
  LandPlot,
  LineChart,
  type LucideIcon,
  MessageSquareText,
  Minus,
  Newspaper,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { useAssetNews, useCandles } from "@/lib/api";
import type { Driver, Signal } from "@/lib/contracts";
import { cn, formatIST } from "@/lib/utils";

// Humanised regime label + a one-line read used as the card's "reasoning" tag.
const REGIME_READ: Record<Signal["regime"], string> = {
  bull_trend: "Momentum / trend-following",
  bear_trend: "Downtrend continuation",
  sideways: "Range-bound · mean reversion",
  high_volatility: "Volatility expansion",
  accumulation: "Accumulation base",
  distribution: "Distribution top",
};

const REGIME_LABEL: Record<Signal["regime"], string> = {
  bull_trend: "Bull trend",
  bear_trend: "Bear trend",
  sideways: "Range-bound",
  high_volatility: "High volatility",
  accumulation: "Accumulation",
  distribution: "Distribution",
};

/** Crude asset → category sub-label + icon, driven off the symbol shape. */
function assetMeta(asset: string): { category: string; Icon: LucideIcon } {
  const a = asset.toUpperCase();
  if (/-USD$/.test(a) && /^(BTC|ETH|SOL|BNB|XRP|ADA|DOGE)/.test(a))
    return { category: "Crypto · spot", Icon: Bitcoin };
  if (/USD$|INR$|EUR$|GBP$/.test(a) && a.length <= 6 && !a.includes("-"))
    return { category: "FX pair", Icon: CircleDollarSign };
  if (/^(XAU|XAG|GOLD|SILVER)/.test(a))
    return { category: "Commodities", Icon: LandPlot };
  if (/\.(NS|BO)$/.test(a) || /^(NIFTY|SENSEX)/.test(a))
    return { category: "India equity", Icon: LineChart };
  return { category: "Equity · cash", Icon: LineChart };
}

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

interface SignalCardProps {
  signal: Signal;
  /** Existing journal entry id for this asset, if any. */
  journalId?: string;
  /** Whether the card starts expanded (the first card opens by default). */
  defaultOpen?: boolean;
}

export function SignalCard({ signal, journalId, defaultOpen }: SignalCardProps) {
  const [open, setOpen] = React.useState<boolean>(defaultOpen ?? false);
  const { category, Icon } = assetMeta(signal.asset);

  const tone =
    signal.direction === "BUY"
      ? "emerald"
      : signal.direction === "SELL"
        ? "red"
        : "slate";

  // Hairline accent down the left edge keyed to direction (Sahara restraint).
  const accent =
    tone === "emerald"
      ? "before:bg-emerald-500/70"
      : tone === "red"
        ? "before:bg-red-500/70"
        : "before:bg-border";

  return (
    <article
      className={cn(
        "relative border border-border/60 bg-card transition-colors",
        "before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:content-['']",
        accent,
        "hover:border-foreground/25",
      )}
    >
      <div className="flex flex-col md:flex-row">
        {/* Left rail — header + key metrics. */}
        <div className="w-full border-b border-border/40 bg-secondary/30 p-5 md:w-72 md:shrink-0 md:border-b-0 md:border-r">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center border border-border/60 bg-card">
              <Icon className="h-5 w-5 text-foreground" aria-hidden />
            </div>
            <div className="min-w-0">
              <h3 className="truncate font-serif text-xl leading-none tracking-tight">
                {signal.asset}
              </h3>
              <p className="eyebrow mt-1">{category}</p>
            </div>
          </div>

          {/* Honest framing: ML signals are still calibrating — a high
              confidence % is model certainty, NOT a proven realised edge. */}
          <div className="mt-3">
            <ExperimentalBadge />
          </div>

          <div className="mt-5 space-y-4">
            <div className="flex items-center justify-between">
              <span className="eyebrow">Direction</span>
              <DirectionBadge direction={signal.direction} />
            </div>

            <ConfidenceBar value={signal.confidence} tone={tone} />

            <div className="border-t border-border/40 pt-3">
              <span className="eyebrow">Reference close</span>
              <ReferencePrice asset={signal.asset} />
            </div>
          </div>
        </div>

        {/* Right column — reasoning tag, expansion, news. */}
        <div className="flex min-w-0 flex-1 flex-col p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="inline-flex items-center bg-primary/10 px-2 py-0.5 font-label text-[11px] uppercase tracking-wider text-primary">
                {REGIME_LABEL[signal.regime]}
              </span>
              <span className="truncate text-sm text-muted-foreground">
                {REGIME_READ[signal.regime]} · {signal.horizon_hours}h horizon
              </span>
            </div>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-label={open ? "Collapse signal detail" : "Expand signal detail"}
              className="-mr-1 shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform duration-200",
                  open && "rotate-180",
                )}
              />
            </button>
          </div>

          {/* Collapsible analysis: feature contribution + narrative context. */}
          {open ? (
            <div className="mt-4 grid grid-cols-1 gap-6 border-t border-border/30 pt-4 lg:grid-cols-2">
              <FeatureContribution drivers={signal.drivers} />
              <NarrativeContext
                counterArguments={signal.counter_arguments}
                regimeLabel={REGIME_LABEL[signal.regime]}
              />
            </div>
          ) : null}

          {/* Market intelligence cluster — related news for the asset. */}
          <NewsCluster asset={signal.asset} />

          {/* Footer — timestamp + advisory links (no execution). */}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border/30 pt-3">
            <span className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              {formatIST(signal.generated_at, "dd MMM HH:mm 'IST'")}
              <span className="ml-2 text-muted-foreground/70">
                {signal.model_name}@{signal.model_version}
              </span>
            </span>
            <div className="flex items-center gap-3">
              <Link
                href={"/chat" as never}
                className="inline-flex items-center gap-1 font-label text-[11px] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
              >
                <MessageSquareText className="h-3 w-3" />
                Ask the agent
              </Link>
              {journalId ? (
                <Link
                  href={`/journal?entry=${journalId}` as never}
                  className="inline-flex items-center gap-0.5 font-label text-[11px] uppercase tracking-wider text-primary hover:underline"
                >
                  Journal <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <Link
                  href={"/journal?new=1" as never}
                  className="inline-flex items-center gap-0.5 font-label text-[11px] uppercase tracking-wider text-primary hover:underline"
                >
                  Pre-trade check <ArrowRight className="h-3 w-3" />
                </Link>
              )}
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

// --- Experimental badge -----------------------------------------------------

/**
 * Amber "Experimental" chip surfacing that the ML signal engine is still
 * CALIBRATING. The `Signal` contract carries no per-signal calibration / data-
 * depth field, so this is shown for every signal as an honest, blanket caveat:
 * the confidence % reflects model certainty, NOT realised accuracy. Sahara-
 * styled (label font, muted amber) with a hover/focus tooltip + native title.
 */
const EXPERIMENTAL_TOOLTIP =
  "Model signals are experimental — not investment advice. Confidence reflects model certainty, not realized accuracy.";

function ExperimentalBadge() {
  return (
    <span
      className="group/exp relative inline-flex cursor-help items-center gap-1 border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-label text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-700 dark:text-amber-300"
      tabIndex={0}
      role="note"
      aria-label={EXPERIMENTAL_TOOLTIP}
      title={EXPERIMENTAL_TOOLTIP}
    >
      <FlaskConical className="h-3 w-3" aria-hidden />
      Experimental
      {/* Hover/focus tooltip — appears below the chip, Sahara card styling. */}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-[calc(100%+6px)] z-30 hidden w-60 border border-border/70 bg-popover p-2.5 text-[11px] font-normal normal-case leading-relaxed tracking-normal text-muted-foreground shadow-md group-hover/exp:block group-focus/exp:block"
      >
        {EXPERIMENTAL_TOOLTIP}
      </span>
    </span>
  );
}

// --- Direction badge --------------------------------------------------------

function DirectionBadge({ direction }: { direction: Signal["direction"] }) {
  const Icon =
    direction === "BUY"
      ? TrendingUp
      : direction === "SELL"
        ? TrendingDown
        : Minus;
  const cls =
    direction === "BUY"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40"
      : direction === "SELL"
        ? "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40"
        : "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/40";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-label text-[11px] font-semibold uppercase tracking-widest",
        cls,
      )}
    >
      <Icon className="h-3 w-3" />
      {direction}
    </span>
  );
}

// --- Confidence bar ---------------------------------------------------------

function ConfidenceBar({
  value,
  tone,
}: {
  value: number;
  tone: "emerald" | "red" | "slate";
}) {
  // Bar uses the amber primary (mockup), value text follows direction tone.
  const text =
    tone === "emerald"
      ? "text-emerald-700 dark:text-emerald-400"
      : tone === "red"
        ? "text-red-700 dark:text-red-400"
        : "text-foreground";
  const width = Math.min(100, Math.max(0, value));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="eyebrow">Confidence</span>
        <span className={cn("font-mono text-sm font-semibold tabular-nums", text)}>
          {value}%
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden bg-muted"
        role="progressbar"
        aria-label="Model confidence"
        aria-valuenow={Math.round(width)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full bg-primary transition-all duration-500"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

// --- Reference price (latest close) -----------------------------------------

function ReferencePrice({ asset }: { asset: string }) {
  // ~30 days of daily candles → most recent close as a price reference. This is
  // NOT an order entry (advisory product); it's the last traded close.
  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 30);
    return d.toISOString();
  }, []);
  const { data } = useCandles({ symbol: asset, timeframe: "1d", since });
  const last = data?.[data.length - 1];
  return (
    <div className="mt-0.5 font-mono text-lg font-medium tabular-nums">
      {last ? usdFmt.format(last.close) : <span className="text-muted-foreground">—</span>}
    </div>
  );
}

// --- Feature contribution (drivers) -----------------------------------------

function FeatureContribution({ drivers }: { drivers: Driver[] }) {
  // Sort by magnitude so the strongest driver leads (mockup order).
  const rows = React.useMemo(
    () =>
      [...drivers].sort(
        (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
      ),
    [drivers],
  );
  const max = React.useMemo(
    () => Math.max(0.01, ...rows.map((r) => Math.abs(r.contribution))),
    [rows],
  );

  return (
    <div>
      <h4 className="eyebrow mb-3">Feature contribution</h4>
      {!rows.length ? (
        <div className="border border-dashed p-3 text-center text-[11px] text-muted-foreground">
          No drivers attached to this signal.
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((d, i) => {
            const positive = d.contribution >= 0;
            const pct = (Math.abs(d.contribution) / max) * 100;
            return (
              <div key={`${d.feature}-${i}`} className="space-y-1">
                <div className="flex items-center justify-between gap-2 text-[11px] font-medium">
                  <span className="truncate text-foreground">{d.feature}</span>
                  <span
                    className={cn(
                      "shrink-0 font-mono tabular-nums",
                      positive
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-red-600 dark:text-red-400",
                    )}
                  >
                    {positive ? "+" : "−"}
                    {Math.abs(d.contribution).toFixed(2)}
                  </span>
                </div>
                <div className="flex h-1 w-full overflow-hidden bg-muted">
                  <div
                    className={cn(
                      "h-full",
                      positive ? "bg-emerald-500" : "ml-auto bg-red-500",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- Narrative context (counter-arguments) ----------------------------------

function NarrativeContext({
  counterArguments,
  regimeLabel,
}: {
  counterArguments: Driver[];
  regimeLabel: string;
}) {
  return (
    <div className="border border-border/40 bg-secondary/40 p-4">
      <h4 className="eyebrow mb-2">Narrative context</h4>
      {counterArguments.length ? (
        <>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Counter-arguments the model weighed against this call under the{" "}
            <span className="text-foreground">{regimeLabel.toLowerCase()}</span>{" "}
            regime:
          </p>
          <ul className="mt-2 space-y-1.5">
            {counterArguments.map((c, i) => (
              <li
                key={`${c.feature}-${i}`}
                className="flex items-start justify-between gap-2 text-[11px]"
              >
                <span className="text-foreground/90">{c.feature}</span>
                <span className="shrink-0 font-mono tabular-nums text-red-600 dark:text-red-400">
                  −{Math.abs(c.contribution).toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-xs italic leading-relaxed text-muted-foreground">
          No material counter-arguments recorded — the drivers point one way.
          Treat as advisory and confirm with your own thesis.
        </p>
      )}
    </div>
  );
}

// --- Market intelligence cluster (news) -------------------------------------

function NewsCluster({ asset }: { asset: string }) {
  const { data } = useAssetNews(asset);
  const items = (data ?? []).slice(0, 4);

  return (
    <div className="mt-5 border-t border-border/30 pt-4">
      <div className="eyebrow mb-2 flex items-center gap-1.5">
        <Newspaper className="h-3 w-3" />
        Market intelligence cluster
      </div>
      {!items.length ? (
        <p className="text-[11px] text-muted-foreground">
          No related headlines yet for {asset}.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map((n, i) => (
            <a
              key={n.id ?? `${n.url}-${i}`}
              href={n.url}
              target="_blank"
              rel="noopener noreferrer"
              title={n.source}
              className="group inline-flex max-w-full items-center gap-2 border border-border/50 bg-secondary/30 px-3 py-1.5 transition-colors hover:border-primary"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary/40 transition-colors group-hover:bg-primary" />
              <span className="truncate text-[11px] text-foreground group-hover:text-primary">
                {n.title}
              </span>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground/60">
                {formatIST(n.time, "dd MMM")}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
