"use client";

import * as React from "react";
import Link from "next/link";
import { Microscope } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useEvents } from "@/lib/api";
import { formatIST } from "@/lib/utils";

const KIND_LABEL: Record<string, string> = {
  contract_win: "Contract win",
  earnings_surprise: "Earnings",
  m_and_a: "M&A",
  regulatory: "Regulatory",
  upgrade: "Upgrade",
  downgrade: "Downgrade",
  buyback: "Buyback",
  guidance: "Guidance",
  management: "Management",
  other: "Other",
};

export default function EventsPage() {
  const [days, setDays] = React.useState(30);
  const [minM, setMinM] = React.useState(0);
  const { data, isLoading, error } = useEvents({ days, minMateriality: minM });
  const events = data?.events ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Events"
        description="Catalysts detected from the news PFIP ingests — contract wins, earnings, M&A, rating changes, regulatory. Deterministic keyword extraction; advisory only."
      />

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="eyebrow">Window</span>
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            className={`border px-2.5 py-1 font-mono transition-colors ${
              d === days
                ? "border-foreground bg-foreground text-background"
                : "border-border/50 text-muted-foreground hover:border-foreground/40"
            }`}
          >
            {d}d
          </button>
        ))}
        <span className="eyebrow ml-3">Min materiality</span>
        {[0, 0.6, 0.75].map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMinM(m)}
            className={`border px-2.5 py-1 font-mono transition-colors ${
              m === minM
                ? "border-foreground bg-foreground text-background"
                : "border-border/50 text-muted-foreground hover:border-foreground/40"
            }`}
          >
            {m === 0 ? "all" : m}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load events. {(error as Error).message}
        </div>
      ) : events.length === 0 ? (
        <EmptyState
          title="No catalysts yet"
          description="Events are extracted nightly from entity-linked news. Once news links to your watchlist symbols, catalysts appear here."
        />
      ) : (
        <div className="divide-y divide-border/40 border border-border/60 bg-card">
          {events.map((e) => (
            <div key={e.id} className="flex flex-wrap items-start gap-3 p-4">
              <span className="border border-border/60 bg-secondary/40 px-2 py-0.5 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                {KIND_LABEL[e.kind] ?? e.kind}
              </span>
              <span className="font-mono text-xs font-semibold">{e.ticker}</span>
              <div className="min-w-0 flex-1">
                <div className="text-sm">
                  {e.source_url ? (
                    <a
                      href={e.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:text-primary hover:underline"
                    >
                      {e.title}
                    </a>
                  ) : (
                    e.title
                  )}
                </div>
                <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground">
                  <span>{e.occurred_at ? formatIST(e.occurred_at) : "—"}</span>
                  <span className="font-mono">materiality {e.materiality.toFixed(2)}</span>
                </div>
              </div>
              {e.ticker ? (
                <Link
                  href={`/research?q=${encodeURIComponent(e.ticker)}`}
                  className="inline-flex shrink-0 items-center gap-1 border border-border/60 px-2 py-1 font-label text-[10px] uppercase tracking-wider text-muted-foreground transition-colors hover:border-foreground/50 hover:text-foreground"
                  title={`Deep-research ${e.ticker}`}
                >
                  <Microscope className="h-3 w-3" />
                  Research
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
