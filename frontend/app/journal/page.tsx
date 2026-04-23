"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Plus, TrendingDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PreTradeChecklistDialog } from "@/components/journal/pre-trade-checklist";
import { PostMortemDialog } from "@/components/journal/post-mortem-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { useJournalEntries } from "@/lib/api";
import { formatIST } from "@/lib/utils";
import type { JournalEntry } from "@/lib/contracts";

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

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Decision journal
          </h1>
          <p className="text-sm text-muted-foreground">
            Every new position begins with a 10-item checklist (Appendix B).
            Closing a trade requires a post-mortem (Appendix C).
          </p>
        </div>
        <Button onClick={() => setChecklistOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" /> New entry
        </Button>
      </div>

      <FailurePatternsCard entries={data ?? []} />

      {isLoading ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-36 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load entries: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <EmptyState
          title="No journal entries yet"
          description="Starting a new trade? The 10-item pre-trade checklist walks you through thesis, invalidation, size, and tax impact."
          action={{
            label: "Open checklist",
            onClick: () => setChecklistOpen(true),
          }}
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.map((entry) => (
            <Card
              key={entry.id}
              id={`journal-entry-${entry.id}`}
              className={
                deepLinkedEntry === entry.id
                  ? "ring-2 ring-primary"
                  : undefined
              }
            >
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle className="text-base">
                    {entry.asset}{" "}
                    <Badge
                      variant={
                        entry.direction === "BUY"
                          ? "success"
                          : entry.direction === "SELL"
                            ? "destructive"
                            : "outline"
                      }
                      className="ml-2 text-[10px]"
                    >
                      {entry.direction}
                    </Badge>
                  </CardTitle>
                  <div className="text-xs text-muted-foreground">
                    Opened {formatIST(entry.created_at)}
                  </div>
                </div>
                {entry.closed_at ? (
                  <Badge variant="secondary">Closed</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPostMortemFor(entry.id)}
                  >
                    Close
                  </Button>
                )}
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div>
                  <span className="text-xs text-muted-foreground">
                    Thesis:
                  </span>{" "}
                  {entry.pre_trade.thesis}
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">
                    Invalidation:
                  </span>{" "}
                  {entry.pre_trade.invalidation}
                </div>
                <div className="text-xs text-muted-foreground">
                  Size {entry.pre_trade.position_size_pct}% · Horizon{" "}
                  {entry.pre_trade.time_horizon} · Conviction{" "}
                  {entry.pre_trade.conviction_score}/10
                </div>
                {entry.post_mortem ? (
                  <div className="mt-2 rounded-md bg-muted/50 p-2 text-xs">
                    <div>
                      P&amp;L: {entry.post_mortem.outcome_pnl_pct.toFixed(2)}%
                    </div>
                    <div className="italic text-muted-foreground">
                      {entry.post_mortem.lessons}
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
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

/**
 * Aggregates closed entries' post-mortems into a simple "top 3 failure
 * patterns" card. We key off `thesis_correct = false` and dedupe by
 * stemmed first-word of the `what_didnt` field as a lightweight pattern tag.
 *
 * TODO(user): swap this with backend-computed tags when `/journal/patterns`
 * exists.
 */
function FailurePatternsCard({ entries }: { entries: JournalEntry[] }) {
  const counts = React.useMemo(() => {
    const map = new Map<string, number>();
    const now = new Date();
    const cutoff = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    entries.forEach((e) => {
      if (!e.post_mortem) return;
      if (e.closed_at && new Date(e.closed_at) < cutoff) return;
      if (e.post_mortem.thesis_correct) return;
      const raw = e.post_mortem.what_didnt?.trim().toLowerCase();
      if (!raw) return;
      const key = raw.split(/[.,;]/)[0]?.slice(0, 60) || raw.slice(0, 60);
      map.set(key, (map.get(key) ?? 0) + 1);
    });
    return [...map.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
  }, [entries]);

  if (!counts.length) return null;

  return (
    <Card className="border-amber-500/30 bg-amber-500/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingDown className="h-4 w-4 text-amber-500" />
          Top failure patterns this month
        </CardTitle>
        <CardDescription>
          Drawn from post-mortems where the thesis was wrong.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="space-y-1 text-sm">
          {counts.map(([pattern, count], i) => (
            <li
              key={pattern}
              className="flex items-center justify-between rounded-md border bg-background p-2"
            >
              <span className="truncate">
                <span className="mr-2 font-mono text-xs text-muted-foreground">
                  #{i + 1}
                </span>
                {pattern}
              </span>
              <Badge variant="outline">×{count}</Badge>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
