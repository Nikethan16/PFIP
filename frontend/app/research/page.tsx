"use client";

import * as React from "react";
import { Microscope, Search } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Markdown } from "@/components/shared/markdown";
import { useResearch } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Deep Research (Phase 6). Type any company → PFIP resolves the ticker, gathers
 * fundamentals/filings/price/news, and writes a cited decision-support dossier.
 */
export default function ResearchPage() {
  const [query, setQuery] = React.useState("");
  const research = useResearch();
  const d = research.data;

  const run = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q) research.mutate({ query: q });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Deep Research"
        description="Type any company — PFIP resolves the ticker, gathers fundamentals, filings, price and news, and writes a cited decision-support dossier (not advice)."
      />

      <form onSubmit={run} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Waree Energies · Reliance Industries · NVIDIA"
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={research.isPending} className="gap-2">
          <Microscope className="h-4 w-4" />
          {research.isPending ? "Researching…" : "Research"}
        </Button>
      </form>

      {research.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(research.error as Error).message}
        </div>
      ) : null}

      {research.isPending && !d ? (
        <div className="text-sm text-muted-foreground">
          Resolving ticker, gathering evidence, writing the dossier… (a few seconds)
        </div>
      ) : null}

      {d ? (
        <div className="space-y-5">
          {/* Resolution + performance header */}
          <div className="flex flex-wrap items-center gap-3 border border-border/60 bg-card p-4">
            <div className="font-serif text-xl tracking-tight">
              {d.resolved?.company ?? d.query}
            </div>
            {(d.matched_symbol ?? d.resolved?.ticker) ? (
              <span className="border border-border/60 bg-secondary/40 px-2 py-0.5 font-mono text-xs">
                {d.matched_symbol ?? d.resolved?.ticker}
              </span>
            ) : null}
            <span
              className={cn(
                "px-2 py-0.5 font-label text-[10px] uppercase tracking-wider",
                d.is_tracked
                  ? "border border-emerald-600/30 bg-emerald-600/5 text-emerald-700 dark:text-emerald-400"
                  : "border border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-400",
              )}
            >
              {d.is_tracked ? "Tracked" : "Not tracked"}
            </span>
            {d.performance ? (
              <div className="ml-auto flex gap-4 font-mono text-xs tabular-nums">
                <Perf label="1M" v={d.performance.ret_1m_pct} />
                <Perf label="3M" v={d.performance.ret_3m_pct} />
                <Perf label="1Y" v={d.performance.ret_1y_pct} />
              </div>
            ) : null}
          </div>

          {d.suggest_add_to_watchlist ? (
            <div className="border border-amber-500/40 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-700 dark:text-amber-400">
              Not in your tracked universe yet — add{" "}
              <span className="font-mono">{d.resolved?.ticker}</span> to the watchlist for full
              fundamentals + price history, then re-run for a richer dossier.
            </div>
          ) : null}

          {/* The dossier */}
          <section className="border border-border/60 bg-card p-5">
            <Markdown>{d.dossier_markdown}</Markdown>
          </section>

          {/* Recent news evidence */}
          {d.news?.length ? (
            <section className="border border-border/60 bg-card p-5">
              <div className="eyebrow mb-2">Recent news ({d.news.length})</div>
              <ul className="space-y-1.5 text-sm">
                {d.news.slice(0, 8).map((n, i) => (
                  <li key={i}>
                    <a
                      href={n.url}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:text-primary"
                    >
                      {n.title}
                    </a>{" "}
                    <span className="text-xs text-muted-foreground">
                      · {n.source} · {n.time.slice(0, 10)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <p className="text-[11px] text-muted-foreground">{d.disclaimer}</p>
        </div>
      ) : null}
    </div>
  );
}

function Perf({ label, v }: { label: string; v: number | null | undefined }) {
  if (v == null) return <span className="text-muted-foreground">{label} —</span>;
  const pos = v >= 0;
  return (
    <span className={pos ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
      {label} {pos ? "+" : ""}
      {v}%
    </span>
  );
}
