"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  Clock,
  Filter,
  LayoutGrid,
  List,
  Minus,
  Newspaper,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DriverChart } from "@/components/signals/driver-chart";
import { RegimeBadge } from "@/components/shared/regime-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { useAssetNews, useJournalEntries, useSignals } from "@/lib/api";
import { cn, confidenceTone, formatIST } from "@/lib/utils";
import type { Regime, Signal } from "@/lib/contracts";

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

export default function SignalsPage() {
  const { data, isLoading, error } = useSignals();
  const { data: journal } = useJournalEntries();

  const [assetFilter, setAssetFilter] = React.useState("");
  const [regimeFilter, setRegimeFilter] = React.useState<string>("all");
  const [directionFilter, setDirectionFilter] = React.useState<string>("all");
  const [minConfidence, setMinConfidence] = React.useState<number>(0);
  /**
   * Stitch design defines a Cards ↔ Table toggle next to the filters.
   * Cards is the default for dense scanning; Table is for power filtering
   * across many signals.
   */
  const [view, setView] = React.useState<"cards" | "table">("cards");

  const journalBySymbol = React.useMemo(() => {
    const map = new Map<string, string>();
    (journal ?? []).forEach((e) => map.set(e.asset, e.id));
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

  return (
    <div className="space-y-4">
      <PageHeader
        title="Signals"
        description="Latest typed signals from the model registry — direction, confidence, drivers, and counter-arguments."
      />

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
        <div className="flex items-center gap-1 rounded-md border bg-background p-0.5 text-xs">
          {MIN_CONFIDENCES.map((c) => (
            <button
              key={c.label}
              type="button"
              onClick={() => setMinConfidence(c.value)}
              className={cn(
                "rounded px-2 py-1 transition-colors",
                minConfidence === c.value
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
        {/* Cards ↔ Table toggle (Stitch parity). */}
        <div className="ml-auto flex items-center gap-1 rounded-md border bg-background p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setView("cards")}
            className={cn(
              "flex items-center gap-1 rounded px-2 py-1 transition-colors",
              view === "cards"
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/60",
            )}
            aria-pressed={view === "cards"}
          >
            <LayoutGrid className="h-3 w-3" />
            Cards
          </button>
          <button
            type="button"
            onClick={() => setView("table")}
            className={cn(
              "flex items-center gap-1 rounded px-2 py-1 transition-colors",
              view === "table"
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/60",
            )}
            aria-pressed={view === "table"}
          >
            <List className="h-3 w-3" />
            Table
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load signals: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <EmptyState
          title="No signals yet"
          description="No data yet — once the model pipeline runs this will populate. Kick off the backtest + calibration flows in the backend to bootstrap."
        />
      ) : !filtered.length ? (
        <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          No signals match your filter.
        </div>
      ) : view === "cards" ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((s, i) => (
            <SignalCard
              key={`${s.asset}-${s.generated_at}-${i}`}
              signal={s}
              journalId={journalBySymbol.get(s.asset)}
            />
          ))}
        </div>
      ) : (
        <SignalsTable signals={filtered} />
      )}
    </div>
  );
}

/** Dense table view of signals — Stitch parity for power filtering. */
function SignalsTable({ signals }: { signals: Signal[] }) {
  return (
    <div className="overflow-hidden rounded-md border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Symbol</th>
            <th className="px-3 py-2 text-left font-medium">Direction</th>
            <th className="px-3 py-2 text-left font-medium">Regime</th>
            <th className="px-3 py-2 text-right font-medium">Confidence</th>
            <th className="px-3 py-2 text-left font-medium">Generated</th>
            <th className="px-3 py-2 text-left font-medium">Model</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s, i) => {
            const toneClass =
              s.direction === "BUY"
                ? "text-emerald-600 dark:text-emerald-400"
                : s.direction === "SELL"
                  ? "text-red-600 dark:text-red-400"
                  : "text-muted-foreground";
            const Arrow =
              s.direction === "BUY"
                ? TrendingUp
                : s.direction === "SELL"
                  ? TrendingDown
                  : Minus;
            return (
              <tr
                key={`${s.asset}-${s.generated_at}-${i}`}
                className="border-t hover:bg-accent/40 transition-colors"
              >
                <td className="px-3 py-2 font-mono text-xs">{s.asset}</td>
                <td className={cn("px-3 py-2 font-medium", toneClass)}>
                  <span className="inline-flex items-center gap-1">
                    <Arrow className="h-3 w-3" />
                    {s.direction}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <RegimeBadge regime={s.regime} size="sm" />
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {Math.round(s.confidence)}%
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {formatIST(s.generated_at)}
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {s.model_name ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SignalCard({
  signal,
  journalId,
}: {
  signal: Signal;
  journalId: string | undefined;
}) {
  const tone =
    signal.direction === "BUY"
      ? "emerald"
      : signal.direction === "SELL"
        ? "red"
        : "slate";
  const Icon =
    signal.direction === "BUY"
      ? TrendingUp
      : signal.direction === "SELL"
        ? TrendingDown
        : Minus;
  const ringColor =
    tone === "emerald"
      ? "border-emerald-500/40 hover:border-emerald-500/60"
      : tone === "red"
        ? "border-red-500/40 hover:border-red-500/60"
        : "border-border hover:border-foreground/30";

  return (
    <Card className={cn("flex flex-col transition-colors", ringColor)}>
      <CardHeader className="space-y-2 pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-1.5 font-mono text-sm">
              {signal.asset}
            </CardTitle>
            <CardDescription className="mt-0.5 text-[11px]">
              {signal.horizon_hours}h horizon
            </CardDescription>
          </div>
          <DirectionBadge direction={signal.direction} icon={Icon} />
        </div>
        <ConfidenceBar value={signal.confidence} />
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 pt-0 text-xs">
        <div className="flex items-center gap-2">
          <RegimeBadge regime={signal.regime} />
          <span className="font-mono text-[10px] text-muted-foreground">
            {signal.model_name}@{signal.model_version}
          </span>
        </div>

        <div>
          <div className="eyebrow mb-1.5">
            Top drivers / counter-arguments
          </div>
          <DriverChart
            drivers={signal.drivers.slice(0, 3)}
            counterArguments={signal.counter_arguments.slice(0, 3)}
            height={Math.max(
              80,
              (Math.min(signal.drivers.length, 3) +
                Math.min(signal.counter_arguments.length, 3)) *
                20,
            )}
          />
        </div>

        <NewsLinks asset={signal.asset} />

        <div className="mt-auto flex items-center justify-between border-t pt-2 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formatIST(signal.generated_at, "dd MMM HH:mm")}
          </span>
          {journalId ? (
            <Link
              href={`/journal?entry=${journalId}` as never}
              className="inline-flex items-center gap-0.5 text-primary hover:underline"
            >
              Journal <ArrowRight className="h-3 w-3" />
            </Link>
          ) : (
            <Link
              href={`/journal?new=1` as never}
              className="hover:text-foreground hover:underline"
            >
              Log trade →
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function DirectionBadge({
  direction,
  icon: Icon,
}: {
  direction: Signal["direction"];
  icon: typeof TrendingUp;
}) {
  const cls =
    direction === "BUY"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40"
      : direction === "SELL"
        ? "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40"
        : "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/40";
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
        cls,
      )}
    >
      <Icon className="h-3 w-3" />
      {direction}
    </Badge>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const tone = confidenceTone(value);
  const bg =
    tone === "emerald"
      ? "bg-emerald-500"
      : tone === "amber"
        ? "bg-amber-500"
        : "bg-red-500";
  const text =
    tone === "emerald"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "amber"
        ? "text-amber-600 dark:text-amber-400"
        : "text-red-600 dark:text-red-400";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="eyebrow">Confidence</span>
        <span className={cn("font-num text-xs font-semibold", text)}>
          {value}%
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
        <div
          className={cn("h-full transition-all", bg)}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

function NewsLinks({ asset }: { asset: string }) {
  const { data } = useAssetNews(asset);
  const top = (data ?? []).slice(0, 2);
  if (!top.length) return null;
  return (
    <div>
      <div className="eyebrow mb-1 flex items-center gap-1">
        <Newspaper className="h-2.5 w-2.5" />
        Recent context
      </div>
      <ul className="space-y-1">
        {top.map((n) => (
          <li key={n.id}>
            <a
              href={n.url}
              target="_blank"
              rel="noopener noreferrer"
              className="line-clamp-2 text-[11px] leading-snug text-muted-foreground hover:text-foreground hover:underline"
              title={n.source}
            >
              {n.title}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
