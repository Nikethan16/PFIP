"use client";

import * as React from "react";

import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useThemes, useThemeBeneficiaries } from "@/lib/api";

export default function ThemesPage() {
  const themes = useThemes();
  const [slug, setSlug] = React.useState<string | null>(null);

  // Default to the first theme once loaded.
  React.useEffect(() => {
    const first = themes.data?.themes?.[0];
    if (!slug && first) setSlug(first.slug);
  }, [themes.data, slug]);

  const detail = useThemeBeneficiaries(slug, 90);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Themes"
        description="Which tracked companies have recent NEWS EXPOSURE to a theme, with the headlines as evidence. A research aid over your watchlist — not a recommendation."
      />

      {/* Theme selector */}
      <div className="flex flex-wrap gap-2">
        {(themes.data?.themes ?? []).map((t) => (
          <button
            key={t.slug}
            type="button"
            onClick={() => setSlug(t.slug)}
            className={`border px-3 py-1.5 text-xs transition-colors ${
              t.slug === slug
                ? "border-foreground bg-foreground text-background"
                : "border-border/50 text-muted-foreground hover:border-foreground/40 hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {detail.isLoading && slug ? (
        <Skeleton className="h-64 w-full" />
      ) : detail.data ? (
        <section className="space-y-4">
          <p className="text-xs text-muted-foreground">
            {detail.data.matched_stories} matching stories · ranked by recency-weighted
            news exposure over {detail.data.window_days} days.
          </p>
          {detail.data.beneficiaries.length === 0 ? (
            detail.data.theme_evidence && detail.data.theme_evidence.length ? (
              <div className="space-y-2">
                <EmptyState
                  title="No tracked-symbol exposure"
                  description="None of your tracked symbols were attributed to this theme, but here are recent headlines driving it — add a relevant name to the watchlist to track exposure."
                />
                <ul className="space-y-1 border border-border/60 bg-card p-4 text-xs text-muted-foreground">
                  {detail.data.theme_evidence.map((ev, i) => (
                    <li key={i} className="truncate">
                      •{" "}
                      {ev.url ? (
                        <a href={ev.url} target="_blank" rel="noreferrer" className="hover:text-primary">
                          {ev.title}
                        </a>
                      ) : (
                        ev.title
                      )}
                      {ev.published_at ? (
                        <span className="ml-1 opacity-70">· {ev.published_at.slice(0, 10)}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <EmptyState
                title="No exposure found"
                description="None of your tracked symbols have recent news matching this theme. Try a longer window or add more symbols to the watchlist."
              />
            )
          ) : (
            <div className="space-y-3">
              {detail.data.beneficiaries.map((b, idx) => (
                <div key={b.ticker} className="border border-border/60 bg-card p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs text-muted-foreground">
                        #{idx + 1}
                      </span>
                      <span className="font-mono text-sm font-semibold">{b.ticker}</span>
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">
                      exposure {b.score.toFixed(2)} · {b.n} stories
                    </span>
                  </div>
                  {b.evidence.length > 0 && (
                    <ul className="mt-2 space-y-1 border-t border-border/40 pt-2 text-xs text-muted-foreground">
                      {b.evidence.map((ev, i) => (
                        <li key={i} className="truncate">
                          •{" "}
                          {ev.url ? (
                            <a
                              href={ev.url}
                              target="_blank"
                              rel="noreferrer"
                              className="hover:text-primary hover:underline"
                            >
                              {ev.title}
                            </a>
                          ) : (
                            ev.title
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">{detail.data.disclaimer}</p>
        </section>
      ) : (
        <Skeleton className="h-64 w-full" />
      )}
    </div>
  );
}
