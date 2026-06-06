"use client";

/**
 * Sahara "Alert Stream" — the Signals page.
 *
 * A vertical stream of rich, expandable signal cards (see SignalCard), with a
 * LIVE | HISTORY toggle and the existing asset / regime / direction / confidence
 * filters restyled to the Sahara terminal aesthetic.
 *
 * Data mapping (every value traces to a real hook — no fabrication):
 *   - LIVE     → useLatestSignals()  (most recent per asset, /signals/latest)
 *   - HISTORY  → useSignals()        (full feed, /signals)
 *   - per-card drivers / counter_arguments / regime / confidence ← Signal
 *   - per-card reference close ← useCandles(asset)   (no entry field on Signal)
 *   - per-card news ← useAssetNews(asset)
 *   - journal link ← useJournalEntries() (existing entry per symbol)
 *   - discipline block ← useJournalPatterns() (preserves journal access)
 *
 * IMPORTANT: ML signal generation is currently GATED OFF, so the feed is empty
 * today. The page renders a strong, honest empty state and will automatically
 * fill with cards once /signals returns rows. ADVISORY-ONLY: no trade execution
 * anywhere — the floating action and per-card CTAs route to the journal / agent.
 */

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Filter,
  History,
  MessageSquareText,
  Radio,
  ScrollText,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SignalCard } from "@/components/signals/signal-card";
import { EmptyState } from "@/components/shared/empty-state";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import {
  useJournalEntries,
  useJournalPatterns,
  useLatestSignals,
  useSignals,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Regime } from "@/lib/contracts";

const REGIMES: Regime[] = [
  "bull_trend",
  "bear_trend",
  "sideways",
  "high_volatility",
  "accumulation",
  "distribution",
];

const MIN_CONFIDENCES: Array<{ label: string; value: number }> = [
  { label: "All", value: 0 },
  { label: "≥ 50%", value: 50 },
  { label: "≥ 70%", value: 70 },
  { label: "≥ 85%", value: 85 },
];

type Feed = "live" | "history";

export default function SignalsPage() {
  const [feed, setFeed] = React.useState<Feed>("live");

  // Both feeds are fetched once and toggled client-side so switching is instant
  // and either can power the empty/loading state without a refetch flash.
  const latest = useLatestSignals();
  const all = useSignals();
  const active = feed === "live" ? latest : all;
  const { data, isLoading, error } = active;

  const { data: journal } = useJournalEntries();

  const [assetFilter, setAssetFilter] = React.useState("");
  const [regimeFilter, setRegimeFilter] = React.useState<string>("all");
  const [directionFilter, setDirectionFilter] = React.useState<string>("all");
  const [minConfidence, setMinConfidence] = React.useState<number>(0);

  const journalBySymbol = React.useMemo(() => {
    const map = new Map<string, string>();
    (journal ?? []).forEach((e) => map.set(e.symbol, e.id));
    return map;
  }, [journal]);

  const filtered = React.useMemo(() => {
    if (!data) return [];
    const q = assetFilter.trim().toLowerCase();
    return data.filter((s) => {
      if (q && !s.asset.toLowerCase().includes(q)) return false;
      if (regimeFilter !== "all" && s.regime !== regimeFilter) return false;
      if (directionFilter !== "all" && s.direction !== directionFilter)
        return false;
      if (s.confidence < minConfidence) return false;
      return true;
    });
  }, [data, assetFilter, regimeFilter, directionFilter, minConfidence]);

  const hasFilters =
    assetFilter.trim() !== "" ||
    regimeFilter !== "all" ||
    directionFilter !== "all" ||
    minConfidence !== 0;

  return (
    <div className="space-y-6">
      {/* Header — serif "Alert Stream" + advisory eyebrow + LIVE|HISTORY. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Calibrated signals // advisory only
            <FreshnessBadge sources={["signal_inference_daily", "calibration_daily"]} />
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Alert Stream
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Typed signals from the model registry — direction, calibrated
            confidence, feature drivers and the model&apos;s own counter-case.
          </p>
        </div>
        <FeedToggle feed={feed} onChange={setFeed} />
      </div>

      {/* Filter rail (Sahara restyle). */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[10rem] max-w-xs flex-1">
          <Filter className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter by asset…"
            value={assetFilter}
            onChange={(e) => setAssetFilter(e.target.value)}
            className="pl-7"
          />
        </div>
        <Select value={regimeFilter} onValueChange={setRegimeFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Regime" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All regimes</SelectItem>
            {REGIMES.map((r) => (
              <SelectItem key={r} value={r}>
                {r.replace(/_/g, " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={directionFilter} onValueChange={setDirectionFilter}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="Direction" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="BUY">BUY</SelectItem>
            <SelectItem value="HOLD">HOLD</SelectItem>
            <SelectItem value="SELL">SELL</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex items-center gap-0.5 border border-border bg-background p-0.5 text-xs">
          {MIN_CONFIDENCES.map((c) => (
            <button
              key={c.label}
              type="button"
              onClick={() => setMinConfidence(c.value)}
              className={cn(
                "px-2 py-1 font-label uppercase tracking-wider transition-colors",
                minConfidence === c.value
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
        {data?.length ? (
          <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular-nums">
            {filtered.length} / {data.length} signal
            {data.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      {/* Signal stream. */}
      {isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-44 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load signals: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <SignalsEmptyState feed={feed} />
      ) : !filtered.length ? (
        <EmptyState
          icon={Filter}
          title="No signals match your filter"
          description={
            hasFilters
              ? "Loosen the asset, regime, direction or confidence filters to see more."
              : undefined
          }
        />
      ) : (
        <div className="space-y-4 pb-4">
          {filtered.map((s, i) => (
            <SignalCard
              key={`${s.asset}-${s.generated_at}-${i}`}
              signal={s}
              journalId={journalBySymbol.get(s.asset)}
              defaultOpen={i === 0}
            />
          ))}
        </div>
      )}

      {/* Discipline check — preserves journal access as a secondary block. */}
      <DisciplineCheck />
    </div>
  );
}

// --- LIVE | HISTORY toggle ---------------------------------------------------

function FeedToggle({
  feed,
  onChange,
}: {
  feed: Feed;
  onChange: (f: Feed) => void;
}) {
  return (
    <div
      className="flex items-center gap-1 border border-border bg-secondary/40 p-1"
      role="tablist"
      aria-label="Signal feed"
    >
      <FeedButton
        active={feed === "live"}
        onClick={() => onChange("live")}
        icon={Radio}
        label="Live"
      />
      <FeedButton
        active={feed === "history"}
        onClick={() => onChange("history")}
        icon={History}
        label="History"
      />
    </div>
  );
}

function FeedButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Radio;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 px-4 py-1.5 font-label text-xs uppercase tracking-wider transition-colors",
        active
          ? "bg-card text-primary shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

// --- Empty state (signals gated off) ----------------------------------------

function SignalsEmptyState({ feed }: { feed: Feed }) {
  return (
    <section className="border border-border/60 bg-card">
      <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-secondary/50 text-muted-foreground">
          <Radio className="h-5 w-5" aria-hidden />
        </div>
        <div className="max-w-md space-y-2">
          <h2 className="font-serif text-2xl tracking-tight">
            No signals yet
          </h2>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Signal generation is gated until enough price history accumulates and
            a calibrated model is pinned. The{" "}
            <span className="text-foreground">
              {feed === "live" ? "live" : "history"}
            </span>{" "}
            feed will populate automatically the moment the inference flow emits
            its first calibrated signal — no action needed here.
          </p>
        </div>
        <div className="flex items-center gap-2 border-t border-border/40 pt-4 font-mono text-[11px] text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5 text-primary" />
          Advisory only · signals are guidance, never orders.
        </div>
        <Link
          href={"/chat" as never}
          className="mt-1 inline-flex items-center gap-2 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
        >
          <MessageSquareText className="h-3.5 w-3.5" />
          Ask the agent what to watch
        </Link>
      </div>
    </section>
  );
}

// --- Discipline check (journal failure patterns) ----------------------------

/**
 * Compact "what trips you up" block. Surfaces the backend's journal
 * failure-pattern aggregation as advisory context alongside the signals, and
 * keeps the journal one click away (the old page linked into the journal too).
 */
function DisciplineCheck() {
  const { data, isLoading } = useJournalPatterns({ days: 30, top: 3 });

  return (
    <section className="border border-border/60 bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/40 p-5">
        <div>
          <div className="eyebrow flex items-center gap-1.5">
            <ScrollText className="h-3.5 w-3.5" />
            Discipline check
          </div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Recurring mistakes · 30d
          </h3>
        </div>
        <Link
          href={"/journal" as never}
          className="inline-flex items-center gap-1 font-label text-xs uppercase tracking-wider text-primary hover:underline"
        >
          Open journal
        </Link>
      </div>
      <div className="p-5">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : !data?.length ? (
          <p className="text-xs text-muted-foreground">
            No post-mortems logged yet. Once you close trades with reflections,
            your recurring patterns surface here to sanity-check new signals
            against past mistakes.
          </p>
        ) : (
          <ul className="space-y-2">
            {data.map((p, i) => (
              <li
                key={`${p.pattern}-${i}`}
                className="flex items-center justify-between gap-3 border border-border/50 bg-secondary/30 px-3 py-2"
              >
                <span className="truncate text-sm text-foreground">
                  {p.pattern}
                </span>
                <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
                  ×{p.count}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
