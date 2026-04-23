"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Filter } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
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
import { useJournalEntries, useSignals } from "@/lib/api";
import { cn, confidenceTone, formatIST } from "@/lib/utils";
import type { Regime, Signal } from "@/lib/contracts";

function directionBadge(d: Signal["direction"]) {
  if (d === "BUY") return <Badge variant="success">BUY</Badge>;
  if (d === "SELL") return <Badge variant="destructive">SELL</Badge>;
  return <Badge variant="outline">HOLD</Badge>;
}

const REGIMES: Regime[] = [
  "bull_trend",
  "bear_trend",
  "sideways",
  "high_volatility",
  "accumulation",
  "distribution",
];

export default function SignalsPage() {
  const { data, isLoading, error } = useSignals();
  const { data: journal } = useJournalEntries();

  const [assetFilter, setAssetFilter] = React.useState("");
  const [regimeFilter, setRegimeFilter] = React.useState<string>("all");
  const [directionFilter, setDirectionFilter] = React.useState<string>("all");
  const [expanded, setExpanded] = React.useState<Set<number>>(new Set());

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
      return true;
    });
  }, [data, assetFilter, regimeFilter, directionFilter]);

  const toggleExpand = (i: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Signals</h1>
        <p className="text-sm text-muted-foreground">
          Recent typed signals from the model registry. Expand a row to see
          SHAP drivers + counter-arguments.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[10rem] max-w-xs">
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
      </div>

      {isLoading ? (
        <Skeleton className="h-80 w-full" />
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load signals: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <EmptyState
          title="No signals yet"
          description="Kick off a model run in the backend to populate this. Live signals stream here."
        />
      ) : !filtered.length ? (
        <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          No signals match your filter.
        </div>
      ) : (
        <>
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Asset</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Confidence</TableHead>
                  <TableHead>Horizon</TableHead>
                  <TableHead>Regime</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Generated</TableHead>
                  <TableHead>Journal</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((s, i) => {
                  const journalId = journalBySymbol.get(s.asset);
                  const isOpen = expanded.has(i);
                  return (
                    <React.Fragment key={`${s.asset}-${s.generated_at}-${i}`}>
                      <TableRow className="cursor-pointer" onClick={() => toggleExpand(i)}>
                        <TableCell>
                          {isOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </TableCell>
                        <TableCell className="font-medium">{s.asset}</TableCell>
                        <TableCell>{directionBadge(s.direction)}</TableCell>
                        <TableCell>
                          <ConfidenceBar value={s.confidence} />
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {s.horizon_hours}h
                        </TableCell>
                        <TableCell>
                          <RegimeBadge regime={s.regime} />
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {s.model_name}@{s.model_version}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatIST(s.generated_at)}
                        </TableCell>
                        <TableCell>
                          {journalId ? (
                            <Link
                              href={`/journal?entry=${journalId}` as never}
                              className="text-xs text-primary hover:underline"
                              onClick={(e) => e.stopPropagation()}
                            >
                              View entry
                            </Link>
                          ) : (
                            <span className="text-[11px] text-muted-foreground">
                              —
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                      {isOpen ? (
                        <TableRow>
                          <TableCell />
                          <TableCell colSpan={8} className="bg-muted/20">
                            <SignalDetails signal={s} />
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </React.Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          <ul className="grid gap-3 md:hidden">
            {filtered.map((s, i) => {
              const isOpen = expanded.has(i);
              return (
                <li
                  key={`${s.asset}-${s.generated_at}-${i}`}
                  className="rounded-md border bg-card p-3 text-sm shadow-sm"
                >
                  <button
                    type="button"
                    onClick={() => toggleExpand(i)}
                    className="flex w-full items-center justify-between"
                    aria-expanded={isOpen}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{s.asset}</span>
                        {directionBadge(s.direction)}
                        <Badge variant="outline">{s.confidence}%</Badge>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                        <RegimeBadge regime={s.regime} />
                        <span>{formatIST(s.generated_at, "dd MMM HH:mm")}</span>
                      </div>
                    </div>
                    {isOpen ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </button>
                  {isOpen ? (
                    <div className="mt-3 border-t pt-3">
                      <SignalDetails signal={s} />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
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
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded bg-muted">
        <div
          className={cn("h-full transition-all", bg)}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-xs tabular-nums">{value}%</span>
    </div>
  );
}

function SignalDetails({ signal }: { signal: Signal }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div>
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Drivers (+) · counter-args (-)
        </div>
        <DriverChart
          drivers={signal.drivers}
          counterArguments={signal.counter_arguments}
          height={Math.max(
            140,
            (signal.drivers.length + signal.counter_arguments.length) * 22,
          )}
        />
      </div>
      <div className="space-y-2 text-xs">
        <div className="rounded-md border bg-background p-2">
          <div className="mb-1 font-medium">Supporting drivers</div>
          {signal.drivers.length ? (
            <ul className="space-y-0.5">
              {signal.drivers.map((d, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span>{d.feature}</span>
                  <span className="text-emerald-600 dark:text-emerald-400 tabular-nums">
                    +{d.contribution.toFixed(3)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-muted-foreground">No drivers attached.</div>
          )}
        </div>
        <div className="rounded-md border bg-background p-2">
          <div className="mb-1 font-medium">Counter-arguments</div>
          {signal.counter_arguments.length ? (
            <ul className="space-y-0.5">
              {signal.counter_arguments.map((d, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span>{d.feature}</span>
                  <span className="text-red-600 dark:text-red-400 tabular-nums">
                    {d.contribution.toFixed(3)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-muted-foreground">None recorded.</div>
          )}
        </div>
      </div>
    </div>
  );
}
