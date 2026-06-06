"use client";

/**
 * "What changed today" — single-card pre-emptive dashboard summary.
 *
 * Pulls /changes-today/ on a 5-min refetch and renders four mini-sections:
 *
 *   1. New signals fired in the window
 *   2. Regime flips per tracked symbol
 *   3. Watchlist movers above |z| >= 5σ
 *   4. Top-N news by impact_score
 *
 * Every section gracefully empties out to "nothing here" so the card
 * never shows misleading whitespace.
 *
 * Intentionally not a Tremor or shadcn special component — plain divs
 * + Tailwind utilities so it fits next to the existing dashboard cards
 * without introducing a new layout primitive.
 */

import { ArrowDown, ArrowUp, Newspaper, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useChangesToday } from "@/lib/api";

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Editorial "What Changed Today" shell — serif heading + mono sync stamp. */
function FeedShell({
  syncLabel,
  children,
}: {
  syncLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-border/60 bg-card p-6">
      <div className="mb-6 flex items-center justify-between gap-3">
        <h3 className="font-serif text-2xl italic tracking-tight">
          What Changed Today
        </h3>
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/60">
          {syncLabel ?? "—"}
        </span>
      </div>
      {children}
    </section>
  );
}

export function ChangesTodayCard() {
  const q = useChangesToday({ hours: 24, zThreshold: 5, newsTop: 5 });

  if (q.isLoading) {
    return (
      <FeedShell syncLabel="Syncing…">
        <Skeleton className="h-32 w-full" />
      </FeedShell>
    );
  }

  if (q.error || !q.data) {
    return (
      <FeedShell>
        <div className="text-sm text-destructive">
          Failed to load: {(q.error as Error)?.message ?? "unknown"}
        </div>
      </FeedShell>
    );
  }

  const d = q.data;
  const totalDeltas =
    d.signals.length + d.regime_flips.length + d.movers.length + d.news.length;

  return (
    <FeedShell syncLabel={`Last sync · ${d.window_hours}h window`}>
      <p className="-mt-3 mb-4 text-sm text-muted-foreground">
        {totalDeltas === 0
          ? "All quiet — nothing tripped the thresholds."
          : `${totalDeltas} item${totalDeltas === 1 ? "" : "s"} worth a look.`}
      </p>
      <div className="space-y-4 text-sm">
        {d.signals.length > 0 && (
          <Section
            title="New signals"
            icon={<TrendingUp className="h-3.5 w-3.5 text-blue-500" />}
          >
            <ul className="space-y-1">
              {d.signals.slice(0, 5).map((s, i) => (
                <li
                  key={`${s.symbol}-${i}`}
                  className="flex items-center justify-between border border-border/50 bg-secondary/30 p-2 hover-tile"
                >
                  <span>
                    <Badge
                      variant={
                        s.direction === "BUY"
                          ? "success"
                          : s.direction === "SELL"
                            ? "destructive"
                            : "outline"
                      }
                      className="mr-2 text-[10px]"
                    >
                      {s.direction}
                    </Badge>
                    {s.symbol}
                  </span>
                  <span className="text-xs text-muted-foreground font-num">
                    conf {(s.confidence * 100).toFixed(0)}% ·{" "}
                    {formatTime(s.generated_at)}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {d.regime_flips.length > 0 && (
          <Section title="Regime flips" icon={null}>
            <ul className="space-y-1">
              {d.regime_flips.slice(0, 5).map((f, i) => (
                <li
                  key={`${f.symbol}-${i}`}
                  className="flex items-center justify-between border border-border/50 bg-secondary/30 p-2 hover-tile"
                >
                  <span>
                    <span className="font-mono text-xs">{f.symbol}</span>:{" "}
                    {f.from_regime ?? "—"} → <strong>{f.to_regime}</strong>
                  </span>
                  <span className="text-xs text-muted-foreground font-num">
                    {(f.confidence * 100).toFixed(0)}% · {formatTime(f.since)}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {d.movers.length > 0 && (
          <Section title="5σ movers" icon={null}>
            <ul className="space-y-1">
              {d.movers.slice(0, 5).map((m) => (
                <li
                  key={m.symbol}
                  className="flex items-center justify-between border border-border/50 bg-secondary/30 p-2 hover-tile"
                >
                  <span className="font-mono text-xs">{m.symbol}</span>
                  <span
                    className={`text-xs font-num inline-flex items-center gap-1 ${
                      m.return_pct >= 0
                        ? "text-green-600 dark:text-green-400"
                        : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {m.return_pct >= 0 ? (
                      <ArrowUp className="h-3 w-3" />
                    ) : (
                      <ArrowDown className="h-3 w-3" />
                    )}
                    {m.return_pct.toFixed(2)}% (z {m.z_score.toFixed(1)})
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {d.news.length > 0 && (
          <Section
            title="Top news by impact"
            icon={<Newspaper className="h-3.5 w-3.5 text-muted-foreground" />}
          >
            <ul className="space-y-1">
              {d.news.slice(0, 5).map((n, i) => (
                <li
                  key={`${n.title}-${i}`}
                  className="flex items-start gap-2 border border-border/50 bg-secondary/30 p-2 hover-tile"
                >
                  <Badge variant="outline" className="text-[10px] shrink-0">
                    {n.impact_score}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    {n.url ? (
                      <a
                        href={n.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-foreground hover:underline truncate block"
                      >
                        {n.title}
                      </a>
                    ) : (
                      <div className="truncate">{n.title}</div>
                    )}
                    <div className="text-[11px] text-muted-foreground">
                      {n.source} · {formatTime(n.published_at)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {totalDeltas === 0 && (
          <div className="text-xs text-muted-foreground">
            Empty deltas means: no new signals, no regime flips, no 5σ
            movers, no high-impact news in the last {d.window_hours}h.
          </div>
        )}
      </div>
    </FeedShell>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="eyebrow mb-1.5 flex items-center gap-1.5">
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}
