"use client";

import * as React from "react";
import { CalendarRange, FileText, RefreshCw } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/shared/markdown";
import { EmptyState } from "@/components/shared/empty-state";
import { useArxivDigest, useWeeklyReview } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Agent digest cards — the weekly review + arXiv research digest. Both back onto
 * markdown endpoints (`/agent/weekly-review`, `/agent/arxiv-digest`) and render
 * via the shared `Markdown` component, mirroring the morning-brief card's
 * loading / error / empty / data branches in the editorial Sahara chrome.
 */
export function DigestCards() {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <WeeklyReviewCard />
      <ArxivDigestCard />
    </div>
  );
}

function WeeklyReviewCard() {
  const { data, isLoading, error, refetch, isFetching } = useWeeklyReview();
  return (
    <DigestShell
      eyebrow="Agent · weekly"
      title="Weekly review"
      icon={<CalendarRange className="h-3.5 w-3.5" />}
      meta={data ? `Week ${data.week}` : null}
      onRefresh={() => refetch()}
      refreshing={isFetching}
    >
      <DigestBody
        isLoading={isLoading}
        error={error}
        markdown={data?.markdown}
        emptyHint="The weekly review hasn't been generated yet. It summarises closed positions and the week's signals."
        onRetry={() => refetch()}
        footer={
          data ? (
            <DigestFooter
              usedLlm={data.used_llm}
              stats={[
                `${data.closed_count} closed`,
                `${data.signal_count} signals`,
              ]}
            />
          ) : null
        }
      />
    </DigestShell>
  );
}

function ArxivDigestCard() {
  const { data, isLoading, error, refetch, isFetching } = useArxivDigest();
  return (
    <DigestShell
      eyebrow="Agent · research"
      title="arXiv digest"
      icon={<FileText className="h-3.5 w-3.5" />}
      meta={data ? `Week ${data.week}` : null}
      onRefresh={() => refetch()}
      refreshing={isFetching}
    >
      <DigestBody
        isLoading={isLoading}
        error={error}
        markdown={data?.markdown}
        emptyHint="No research digest yet. This rounds up recent quant-finance / ML papers relevant to your strategy."
        onRetry={() => refetch()}
        footer={
          data ? (
            <DigestFooter
              usedLlm={data.used_llm}
              stats={[`${data.papers_count} papers`]}
            />
          ) : null
        }
      />
    </DigestShell>
  );
}

function DigestShell({
  eyebrow,
  title,
  icon,
  meta,
  onRefresh,
  refreshing,
  children,
}: {
  eyebrow: string;
  title: string;
  icon: React.ReactNode;
  meta: string | null;
  onRefresh: () => void;
  refreshing: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col border border-border/60 bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-border/40 p-5">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            {icon}
            {eyebrow}
          </div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">{title}</h3>
        </div>
        <div className="flex flex-col items-end gap-1 text-right">
          {meta ? (
            <span className="font-mono text-[11px] text-muted-foreground">
              {meta}
            </span>
          ) : null}
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1 font-label text-[11px] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground disabled:opacity-60"
            aria-label={`Refresh ${title}`}
          >
            <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>
      <div className="flex-1 p-5">{children}</div>
    </section>
  );
}

function DigestBody({
  isLoading,
  error,
  markdown,
  emptyHint,
  onRetry,
  footer,
}: {
  isLoading: boolean;
  error: unknown;
  markdown: string | undefined;
  emptyHint: string;
  onRetry: () => void;
  footer: React.ReactNode;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="border border-destructive/40 bg-destructive/5 p-3 text-sm">
        <div className="font-medium text-destructive">
          Couldn&apos;t load digest
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {(error as Error).message} — the agent may still be warming up.
        </div>
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 inline-flex items-center gap-1 border border-border px-3 py-1.5 font-label text-[11px] uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
        >
          <RefreshCw className="h-3 w-3" /> Retry
        </button>
      </div>
    );
  }
  if (!markdown || !markdown.trim()) {
    return <EmptyState title="Nothing yet" description={emptyHint} />;
  }
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      <Markdown>{markdown}</Markdown>
      {footer}
    </div>
  );
}

function DigestFooter({
  usedLlm,
  stats,
}: {
  usedLlm: boolean;
  stats: string[];
}) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border/40 pt-3 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
      {stats.map((s) => (
        <span
          key={s}
          className="border border-border/60 bg-secondary/40 px-2 py-0.5"
        >
          {s}
        </span>
      ))}
      <span className="border border-border/60 bg-secondary/40 px-2 py-0.5">
        {usedLlm ? "LLM" : "rule-based"}
      </span>
    </div>
  );
}
