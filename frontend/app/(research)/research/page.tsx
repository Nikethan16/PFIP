"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Microscope, Search } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ResearchResult } from "@/components/research/research-result";
import { useResearch } from "@/lib/api";

/**
 * Deep Research (Phase 6 + P4 flagship). Type any company → PFIP resolves the
 * ticker, gathers fundamentals / 5-yr statements / peers / price / news, and
 * writes a cited decision-support dossier.
 *
 * The result renders in one of two visual directions (warm Sahara vs cool
 * terminal) via the toggle — this is the P4 design-direction sign-off surface.
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
        description="Type any company — PFIP resolves the ticker, gathers fundamentals, 5-yr statements, peers, price and news, and writes a cited decision-support dossier (not advice)."
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

      {d ? <ResearchResult data={d} variant="warm" /> : null}
    </div>
  );
}
