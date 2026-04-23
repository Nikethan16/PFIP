"use client";

import { RefreshCw, Sparkles } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useMorningBrief } from "@/lib/api";
import { formatIST } from "@/lib/utils";
import { Markdown } from "@/components/shared/markdown";
import { StaleBadge } from "@/components/shared/stale-badge";
import { EmptyState } from "@/components/shared/empty-state";

/**
 * The first thing the user reads each morning. Renders the markdown brief
 * returned by `/agent/morning-brief` via `react-markdown` + GFM + highlight.
 *
 * Branches:
 *   loading  → skeleton
 *   error    → inline alert + retry button
 *   empty    → empty-state CTA
 *   data     → rendered markdown + headline_items list
 */
export function BriefCard() {
  const { data, isLoading, error, refetch, isFetching } = useMorningBrief();

  return (
    <Card className="border-primary/30 bg-gradient-to-br from-primary/10 to-transparent">
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Morning brief
          </CardTitle>
          <CardDescription>
            {/* TODO(user): tune the agent persona + brief tone in
                backend/pfip/agents/prompts.py */}
            Your overnight market digest + today&apos;s watch items.
          </CardDescription>
        </div>
        <div className="flex flex-col items-end gap-1 text-right">
          {data ? (
            <>
              <div className="text-xs text-muted-foreground">
                {formatIST(data.generated_at, "dd MMM")} ·{" "}
                {formatIST(data.generated_at, "HH:mm 'IST'")}
              </div>
              <StaleBadge updatedAt={data.generated_at} warnAfterMins={24 * 60} />
            </>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="h-7 gap-1 text-[11px]"
            aria-label="Refresh morning brief"
          >
            <RefreshCw
              className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
            <div className="font-medium text-destructive">
              Couldn&apos;t load brief
            </div>
            <div className="text-xs text-muted-foreground">
              {(error as Error).message} — the morning-brief agent may still be
              warming up. It usually publishes by 08:00 IST.
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-2 gap-1"
              onClick={() => refetch()}
            >
              <RefreshCw className="h-3 w-3" /> Retry
            </Button>
          </div>
        ) : !data || !data.markdown.trim() ? (
          <EmptyState
            title="No brief yet"
            description="The 08:00 IST job hasn't produced today's digest. Check back shortly, or kick off the flow manually from the backend."
          />
        ) : (
          <div className="space-y-3 text-sm leading-relaxed">
            <Markdown>{data.markdown}</Markdown>
            {data.headline_items.length ? (
              <ul className="mt-4 space-y-1 border-t pt-3">
                {data.headline_items.map((item) => (
                  <li key={item.symbol} className="flex gap-2 text-xs">
                    <span className="font-mono font-semibold text-primary">
                      {item.symbol}
                    </span>
                    <span className="text-muted-foreground">— {item.note}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
