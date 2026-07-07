"use client";

/**
 * Corporate calendar (D6) — corporate announcements + regulatory filings for
 * the names you hold or watch, grouped by date. Data is real ingested
 * announcements/filings (NSE / SEC), not forward earnings estimates.
 */

import * as React from "react";
import Link from "next/link";
import { CalendarDays, ExternalLink, FileText, Landmark } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useCalendar, type CalendarEvent } from "@/lib/api";
import { cn } from "@/lib/utils";

const CATEGORY_META: Record<string, { label: string; icon: typeof FileText }> = {
  corp_announcement: { label: "Announcement", icon: Landmark },
  sec_filing: { label: "SEC filing", icon: FileText },
};

function fmtDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function CalendarPage() {
  const { data, isLoading, error } = useCalendar(45);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Corporate calendar"
        description="Announcements and filings for the names you hold or watch, most recent first. Real ingested events — not forward earnings estimates."
      />

      {error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(error as Error).message}
        </div>
      ) : isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : !data || !data.days.length ? (
        <EmptyState
          icon={CalendarDays}
          title="No corporate events yet"
          description={
            data && !data.scoped_to_holdings
              ? "Add names to your watchlist or holdings, and once the ingest picks up their announcements/filings they'll appear here."
              : "No announcements or filings ingested for your names in the last 45 days. This fills in as the nightly ingest runs."
          }
        />
      ) : (
        <div className="space-y-6">
          {!data.scoped_to_holdings ? (
            <p className="text-xs text-muted-foreground">
              Showing the whole feed — add holdings/watchlist names to scope this to yours.
            </p>
          ) : null}
          {data.days.map((day) => (
            <section key={day.date} className="space-y-2">
              <div className="sticky top-0 z-10 flex items-center gap-2 bg-background/95 py-1 backdrop-blur">
                <CalendarDays className="h-3.5 w-3.5 text-primary" />
                <span className="font-label text-xs uppercase tracking-wider">{fmtDay(day.date)}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {day.events.length} event{day.events.length === 1 ? "" : "s"}
                </span>
              </div>
              <ul className="space-y-2">
                {day.events.map((e, i) => (
                  <EventRow key={`${e.url ?? e.title}-${i}`} event={e} />
                ))}
              </ul>
            </section>
          ))}
          {data.disclaimer ? (
            <p className="text-[11px] text-muted-foreground">{data.disclaimer}</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: CalendarEvent }) {
  const meta = CATEGORY_META[event.category] ?? { label: event.category, icon: FileText };
  const Icon = meta.icon;
  return (
    <li className="flex items-start gap-3 border border-border/60 bg-card p-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary/50 text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {event.symbol ? (
            <span className="font-medium">{event.symbol}</span>
          ) : null}
          <span
            className={cn(
              "font-label text-[10px] uppercase tracking-wider",
              event.category === "sec_filing"
                ? "text-blue-700 dark:text-blue-400"
                : "text-amber-700 dark:text-amber-400",
            )}
          >
            {meta.label}
          </span>
        </div>
        <p className="mt-0.5 text-sm leading-snug">{event.title}</p>
      </div>
      {event.url ? (
        <Link
          href={event.url as never}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-0.5 shrink-0 text-muted-foreground hover:text-primary"
          aria-label="Open source"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      ) : null}
    </li>
  );
}
