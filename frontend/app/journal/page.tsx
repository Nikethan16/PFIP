"use client";

/**
 * Sahara "Decision Journal" — the Journal page.
 *
 * An editorial ledger of trade decisions. Every position opens with the 10-item
 * pre-trade checklist (Appendix B) and closes with a post-mortem (Appendix C).
 *
 * Data mapping (every value traces to a real hook — no fabrication):
 *   - entry list       ← useJournalEntries()   (/journal/entries)
 *   - failure patterns ← useJournalPatterns()  (/journal/patterns), with a
 *                        client-side fallback over the same entries
 *   - new entry        ← PreTradeChecklistDialog → useCreateJournalEntry()
 *   - close trade      ← PostMortemDialog → useCloseJournalEntry()
 *
 * The pre-trade checklist dialog still posts the FULL Appendix-B checklist keys
 * unchanged; this file only restyles the surrounding page. Deep links
 * (?new=1, ?entry=<id>) are preserved.
 */

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Check, NotebookPen, Plus, TrendingDown, X } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { PreTradeChecklistDialog } from "@/components/journal/pre-trade-checklist";
import { PostMortemDialog } from "@/components/journal/post-mortem-dialog";
import { useJournalEntries, useJournalPatterns } from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";
import type { JournalEntry } from "@/lib/contracts";

/** Friendly labels for the canonical Appendix-B checklist keys. */
const CHECKLIST_LABELS: Record<string, string> = {
  thesis: "Thesis stated",
  invalidation: "Invalidation defined",
  position_size_pct: "Size set",
  stop_loss_pct: "Stop-loss set",
  time_horizon: "Horizon set",
  correlation_check: "Correlation checked",
  liquidity_check: "Liquidity checked",
  tax_impact_considered: "Tax impact",
  news_check: "News reviewed",
  regime_alignment: "Regime aligned",
  conviction_score: "Conviction scored",
};

function prettyKey(key: string): string {
  return (
    CHECKLIST_LABELS[key] ??
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export default function JournalPage() {
  return (
    <React.Suspense fallback={null}>
      <JournalPageInner />
    </React.Suspense>
  );
}

function JournalPageInner() {
  const { data, isLoading, error } = useJournalEntries();
  const params = useSearchParams();
  const deepLinkedNew = params?.get("new") === "1";
  const deepLinkedEntry = params?.get("entry");

  const [checklistOpen, setChecklistOpen] = React.useState(false);
  const [postMortemFor, setPostMortemFor] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (deepLinkedNew) setChecklistOpen(true);
  }, [deepLinkedNew]);

  React.useEffect(() => {
    if (deepLinkedEntry) {
      // Scroll into view if it's already rendered.
      const el = document.getElementById(`journal-entry-${deepLinkedEntry}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [deepLinkedEntry, data]);

  const openCount = (data ?? []).filter((e) => !e.closed_at).length;
  const closedCount = (data ?? []).length - openCount;

  return (
    <div className="space-y-8">
      {/* Header — serif "Decision Journal" + advisory eyebrow + new entry. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow">Pre-trade discipline // post-mortem loop</div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Decision Journal
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every position opens with a 10-item checklist (Appendix&nbsp;B) and
            closes with an honest post-mortem (Appendix&nbsp;C). Discipline
            compounds.
          </p>
        </div>
        <div className="flex items-center gap-4">
          {data?.length ? (
            <div className="hidden items-center gap-4 sm:flex">
              <CountStat label="Open" value={openCount} />
              <CountStat label="Closed" value={closedCount} />
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => setChecklistOpen(true)}
            className="inline-flex items-center gap-2 bg-primary px-4 py-2 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
          >
            <Plus className="h-3.5 w-3.5" /> New entry
          </button>
        </div>
      </div>

      <FailurePatternsCard entries={data ?? []} />

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-44 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load entries: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <section className="border border-border/60 bg-card">
          <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-secondary/50 text-muted-foreground">
              <NotebookPen className="h-5 w-5" aria-hidden />
            </div>
            <div className="max-w-md space-y-2">
              <h2 className="font-serif text-2xl tracking-tight">
                No entries yet
              </h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Starting a new trade? The 10-item pre-trade checklist walks you
                through thesis, invalidation, size and tax impact before a single
                rupee is committed — and gives you something to grade yourself
                against later.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setChecklistOpen(true)}
              className="mt-1 inline-flex items-center gap-2 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
            >
              <Plus className="h-3.5 w-3.5" />
              Open the checklist
            </button>
          </div>
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.map((entry) => (
            <JournalEntryCard
              key={entry.id}
              entry={entry}
              highlighted={deepLinkedEntry === entry.id}
              onClose={() => setPostMortemFor(entry.id)}
            />
          ))}
        </div>
      )}

      <PreTradeChecklistDialog
        open={checklistOpen}
        onOpenChange={setChecklistOpen}
      />
      <PostMortemDialog
        open={postMortemFor !== null}
        entryId={postMortemFor}
        onOpenChange={(next) => !next && setPostMortemFor(null)}
      />
    </div>
  );
}

function CountStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <div className="eyebrow">{label}</div>
      <div className="font-mono text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

/** One journal entry rendered as an editorial card. */
function JournalEntryCard({
  entry,
  highlighted,
  onClose,
}: {
  entry: JournalEntry;
  highlighted: boolean;
  onClose: () => void;
}) {
  const items = Object.entries(entry.pre_trade_checklist);
  const passed = items.filter(([, v]) => v).length;
  const closed = Boolean(entry.closed_at);

  const directionTone =
    entry.direction === "BUY"
      ? "text-emerald-700 dark:text-emerald-400"
      : entry.direction === "SELL"
        ? "text-red-700 dark:text-red-400"
        : "text-muted-foreground";

  return (
    <article
      id={`journal-entry-${entry.id}`}
      className={cn(
        "flex flex-col border border-border/60 bg-card transition-colors",
        highlighted ? "ring-2 ring-primary" : "hover:border-foreground/20",
      )}
    >
      {/* Card head: symbol + direction + opened-at, close action on the right. */}
      <div className="flex items-start justify-between gap-3 border-b border-border/40 p-5">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h3 className="truncate font-serif text-2xl leading-none tracking-tight">
              {entry.symbol}
            </h3>
            <span
              className={cn(
                "font-label text-xs uppercase tracking-wider",
                directionTone,
              )}
            >
              {entry.direction}
            </span>
          </div>
          <div className="mt-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Opened {formatIST(entry.created_at, "dd MMM yyyy")}
            {entry.closed_at
              ? ` · closed ${formatIST(entry.closed_at, "dd MMM yyyy")}`
              : ""}
          </div>
        </div>
        {closed ? (
          <span className="shrink-0 border border-border/60 px-2.5 py-1 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            Closed
          </span>
        ) : (
          <button
            type="button"
            onClick={onClose}
            title="Close this position and write its post-mortem"
            className="shrink-0 border border-border px-3 py-1.5 font-label text-[10px] uppercase tracking-wider text-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
          >
            Close
          </button>
        )}
      </div>

      <div className="flex-1 space-y-4 p-5">
        {/* Thesis — the editorial centrepiece. */}
        <div>
          <div className="eyebrow mb-1">Thesis</div>
          <p className="font-serif text-sm leading-relaxed text-foreground">
            {entry.thesis}
          </p>
        </div>

        {/* Pre-trade checklist state — chips with tick / cross. */}
        {items.length ? (
          <div>
            <div className="eyebrow mb-2 flex items-center justify-between">
              <span>Pre-trade checklist</span>
              <span className="font-mono tabular-nums text-foreground">
                {passed}/{items.length}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {items.map(([key, ok]) => (
                <span
                  key={key}
                  className={cn(
                    "inline-flex items-center gap-1 border px-2 py-0.5 font-label text-[10px] uppercase tracking-wider",
                    ok
                      ? "border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "border-border/60 bg-secondary/40 text-muted-foreground",
                  )}
                >
                  {ok ? (
                    <Check className="h-2.5 w-2.5" />
                  ) : (
                    <X className="h-2.5 w-2.5" />
                  )}
                  {prettyKey(key)}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {/* Notes. */}
        {entry.notes ? (
          <p className="text-xs text-muted-foreground">{entry.notes}</p>
        ) : null}

        {/* Post-mortem (free-text markdown) — only present once closed. */}
        {entry.post_mortem ? (
          <div className="border-l-2 border-primary/40 bg-secondary/30 px-3 py-2">
            <div className="eyebrow mb-1">Post-mortem</div>
            <p className="whitespace-pre-wrap font-serif text-xs italic leading-relaxed text-muted-foreground">
              {entry.post_mortem}
            </p>
          </div>
        ) : null}
      </div>
    </article>
  );
}

/**
 * Top-3 failure patterns over the trailing 30 days.
 *
 * Primary source is the backend's `GET /journal/patterns` aggregation
 * (post-mortem clustering by first clause, scoped to closed entries in
 * the last N days). If the endpoint isn't reachable or returns empty we
 * fall back to a client-side compute over the supplied entries — same
 * heuristic, just rendered locally so the card still works in demo mode.
 */
function FailurePatternsCard({ entries }: { entries: JournalEntry[] }) {
  const backend = useJournalPatterns({ days: 30, top: 3 });

  const fallback = React.useMemo(() => {
    const map = new Map<string, number>();
    const now = new Date();
    const cutoff = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    entries.forEach((e) => {
      // post_mortem is free-text markdown; cluster by its first clause — the
      // same heuristic the backend /journal/patterns endpoint uses.
      if (!e.post_mortem) return;
      if (e.closed_at && new Date(e.closed_at) < cutoff) return;
      const raw = e.post_mortem.trim().toLowerCase();
      if (!raw) return;
      const key = raw.split(/[.,;\n]/)[0]?.slice(0, 60) || raw.slice(0, 60);
      map.set(key, (map.get(key) ?? 0) + 1);
    });
    return [...map.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
  }, [entries]);

  const counts: [string, number][] = (() => {
    if (backend.data && backend.data.length > 0) {
      return backend.data.map((p) => [p.pattern, p.count] as [string, number]);
    }
    return fallback;
  })();

  // Empty until trades are closed with post-mortems — render an honest, quiet
  // placeholder rather than hiding the block entirely.
  return (
    <section className="border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
          <TrendingDown className="h-3.5 w-3.5" />
          Discipline check
        </div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">
          Top failure patterns · 30d
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Clustered from post-mortems where the thesis was wrong.
        </p>
      </div>
      <div className="p-5">
        {backend.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !counts.length ? (
          <p className="text-xs text-muted-foreground">
            No post-mortems logged yet. Once you close trades with honest
            reflections, your recurring mistakes surface here so new decisions
            can be sanity-checked against past ones.
          </p>
        ) : (
          <ol className="space-y-2">
            {counts.map(([pattern, count], i) => (
              <li
                key={`${pattern}-${i}`}
                className="flex items-center justify-between gap-3 border border-border/50 bg-secondary/30 px-3 py-2"
              >
                <span className="flex min-w-0 items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">
                    #{i + 1}
                  </span>
                  <span className="truncate text-foreground">{pattern}</span>
                </span>
                <span className="shrink-0 border border-border/60 px-2 py-0.5 font-mono text-xs text-muted-foreground tabular-nums">
                  ×{count}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
