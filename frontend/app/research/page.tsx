"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
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
 *
 * Accepts a ``?q=<name>`` query param (used by the "Research this" one-click on
 * the Events feed) — it pre-fills the box and auto-runs the dossier on load.
 */
export default function ResearchPage() {
  return (
    <React.Suspense fallback={null}>
      <ResearchInner />
    </React.Suspense>
  );
}

function ResearchInner() {
  const params = useSearchParams();
  const initialQ = params.get("q")?.trim() ?? "";
  const [query, setQuery] = React.useState(initialQ);
  const research = useResearch();
  const d = research.data;

  const run = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q) research.mutate({ query: q });
  };

  // Auto-run once when arriving with a ?q= param (deep link from Events, etc.).
  const autoRan = React.useRef(false);
  React.useEffect(() => {
    if (initialQ && !autoRan.current) {
      autoRan.current = true;
      research.mutate({ query: initialQ });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQ]);

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
              {d.business_overview?.name ?? d.resolved?.company ?? d.query}
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

          {/* Key fundamentals grid */}
          {d.fundamentals?.key_metrics && Object.keys(d.fundamentals.key_metrics).length ? (
            <section className="border border-border/60 bg-card p-5">
              <div className="eyebrow mb-3 flex items-center gap-2">
                Key fundamentals
                {d.fundamentals_are_live ? (
                  <span className="border border-sky-500/30 bg-sky-500/5 px-1.5 py-0.5 font-label text-[9px] uppercase tracking-wider text-sky-700 dark:text-sky-400">
                    Live · {d.fundamentals.source ?? "fetched"}
                  </span>
                ) : d.fundamentals.source ? (
                  <span className="text-[10px] text-muted-foreground">
                    {d.fundamentals.source}
                    {d.fundamentals.as_of_date ? ` · ${d.fundamentals.as_of_date.slice(0, 10)}` : ""}
                  </span>
                ) : null}
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
                {METRIC_ORDER.filter((k) => d.fundamentals?.key_metrics?.[k.key] != null).map((k) => (
                  <div key={k.key} className="flex flex-col">
                    <dt className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                      {k.label}
                    </dt>
                    <dd className="font-mono text-sm tabular-nums">
                      {k.fmt(d.fundamentals!.key_metrics![k.key] as number)}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
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

/** Compact number (1.2B, 340M, 5.1K) for market cap. */
function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(0);
}
/** Margins/yields arrive either as fractions (0.18) or percents (18) by source. */
const pct = (v: number) => `${(Math.abs(v) <= 1 ? v * 100 : v).toFixed(1)}%`;
const ratio = (v: number) => v.toFixed(2);

const METRIC_ORDER: { key: string; label: string; fmt: (v: number) => string }[] = [
  { key: "market_cap", label: "Market cap", fmt: compact },
  { key: "pe_ratio", label: "P/E", fmt: ratio },
  { key: "pb_ratio", label: "P/B", fmt: ratio },
  { key: "price_to_sales", label: "P/S", fmt: ratio },
  { key: "eps", label: "EPS", fmt: ratio },
  { key: "revenue_growth", label: "Rev growth", fmt: pct },
  { key: "eps_growth", label: "EPS growth", fmt: pct },
  { key: "net_margin", label: "Net margin", fmt: pct },
  { key: "operating_margin", label: "Op margin", fmt: pct },
  { key: "roe", label: "ROE", fmt: pct },
  { key: "roce", label: "ROCE", fmt: pct },
  { key: "roa", label: "ROA", fmt: pct },
  { key: "debt_to_equity", label: "Debt/Equity", fmt: ratio },
  { key: "current_ratio", label: "Current ratio", fmt: ratio },
  { key: "dividend_yield", label: "Div yield", fmt: pct },
  { key: "beta", label: "Beta", fmt: ratio },
  { key: "book_value", label: "Book value", fmt: ratio },
  { key: "52w_high", label: "52w high", fmt: ratio },
  { key: "52w_low", label: "52w low", fmt: ratio },
];

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
