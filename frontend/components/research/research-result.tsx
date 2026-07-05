"use client";

import * as React from "react";

import { Sparkline } from "@/components/charts/sparkline";
import { Markdown } from "@/components/shared/markdown";
import type { ResearchDossier } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Deep Research result, rendered in one of two visual directions so the look
 * can be chosen from the actual page (P4 flagship):
 *
 *  - "warm" — the current Sahara identity (respects app light/dark tokens).
 *  - "cool" — a dark Bloomberg-terminal frame (cyan/slate, dense, mono-first),
 *             self-contained so it reads the same in light or dark mode.
 *
 * Both surface the SAME data — including the new statements trend + peer table
 * — so the comparison is purely aesthetic, not feature-gated.
 */
export type ResearchVariant = "warm" | "cool";

interface Theme {
  frame: string;
  card: string;
  heading: string;
  eyebrow: string;
  label: string;
  value: string;
  pos: string;
  neg: string;
  muted: string;
  chipTracked: string;
  chipUntracked: string;
  chipLive: string;
  chipTicker: string;
  bar: string;
  barTrack: string;
  link: string;
}

const THEMES: Record<ResearchVariant, Theme> = {
  warm: {
    frame: "space-y-5",
    card: "border border-border/60 bg-card p-5",
    heading: "font-serif text-xl tracking-tight",
    eyebrow:
      "font-label text-[10px] uppercase tracking-wider text-primary/80 mb-3 flex items-center gap-2",
    label: "font-label text-[10px] uppercase tracking-wider text-muted-foreground",
    value: "font-mono text-sm tabular-nums",
    pos: "text-emerald-600 dark:text-emerald-400",
    neg: "text-red-600 dark:text-red-400",
    muted: "text-muted-foreground",
    chipTracked:
      "border border-emerald-600/30 bg-emerald-600/5 text-emerald-700 dark:text-emerald-400",
    chipUntracked:
      "border border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-400",
    chipLive: "border border-sky-500/30 bg-sky-500/5 text-sky-700 dark:text-sky-400",
    chipTicker: "border border-border/60 bg-secondary/40 text-foreground",
    bar: "bg-primary/70",
    barTrack: "bg-secondary",
    link: "hover:text-primary",
  },
  cool: {
    frame:
      "space-y-4 rounded-lg bg-slate-950 p-4 text-slate-200 ring-1 ring-slate-800 [--tw-prose-body:theme(colors.slate.300)]",
    card: "rounded-md border border-slate-800 bg-slate-900/60 p-5",
    heading: "font-mono text-lg font-semibold tracking-tight text-cyan-300",
    eyebrow:
      "font-mono text-[10px] uppercase tracking-[0.22em] text-cyan-400/80 mb-3 flex items-center gap-2",
    label: "font-mono text-[10px] uppercase tracking-wider text-slate-500",
    value: "font-mono text-sm tabular-nums text-slate-100",
    pos: "text-emerald-400",
    neg: "text-rose-400",
    muted: "text-slate-500",
    chipTracked: "border border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
    chipUntracked: "border border-amber-400/30 bg-amber-400/10 text-amber-300",
    chipLive: "border border-cyan-400/30 bg-cyan-400/10 text-cyan-300",
    chipTicker: "border border-slate-700 bg-slate-800/60 text-slate-200",
    bar: "bg-cyan-400/80",
    barTrack: "bg-slate-800",
    link: "hover:text-cyan-300",
  },
};

// ---- formatting helpers (shared) -------------------------------------------
function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(0);
}
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
];

const PEER_LABELS: Record<string, string> = {
  pe_ratio: "P/E",
  pb_ratio: "P/B",
  roe: "ROE",
  roce: "ROCE",
  net_margin: "Net margin",
  operating_margin: "Op margin",
  revenue_growth: "Rev growth",
  debt_to_equity: "Debt/Equity",
  dividend_yield: "Div yield",
};
const peerFmt = (k: string, v: number) =>
  ["pe_ratio", "pb_ratio", "debt_to_equity"].includes(k) ? ratio(v) : pct(v);

export function ResearchResult({
  data: d,
  variant,
}: {
  data: ResearchDossier;
  variant: ResearchVariant;
}) {
  const t = THEMES[variant];
  const metrics = d.fundamentals?.key_metrics ?? {};
  const trend = d.statements?.trend ?? [];

  return (
    <div className={t.frame}>
      {/* Resolution + performance header */}
      <div className={cn(t.card, "flex flex-wrap items-center gap-3")}>
        <div className={t.heading}>
          {d.business_overview?.name ?? d.resolved?.company ?? d.query}
        </div>
        {(d.matched_symbol ?? d.resolved?.ticker) ? (
          <span className={cn("px-2 py-0.5 font-mono text-xs", t.chipTicker)}>
            {d.matched_symbol ?? d.resolved?.ticker}
          </span>
        ) : null}
        <span
          className={cn(
            "px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
            d.is_tracked ? t.chipTracked : t.chipUntracked,
          )}
        >
          {d.is_tracked ? "Tracked" : "Not tracked"}
        </span>
        {d.performance ? (
          <div className="ml-auto flex items-center gap-4 font-mono text-xs tabular-nums">
            <Perf t={t} label="1M" v={d.performance.ret_1m_pct} />
            <Perf t={t} label="3M" v={d.performance.ret_3m_pct} />
            <Perf t={t} label="1Y" v={d.performance.ret_1y_pct} />
            {d.performance.as_of ? (
              <span className={cn("text-[10px]", t.muted)}>
                as of {d.performance.as_of.slice(0, 10)}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Key fundamentals */}
      {Object.keys(metrics).length ? (
        <section className={t.card}>
          <div className={t.eyebrow}>
            Key fundamentals
            {d.fundamentals_are_live ? (
              <span className={cn("px-1.5 py-0.5 text-[9px] uppercase tracking-wider", t.chipLive)}>
                Live · {d.fundamentals?.source ?? "fetched"}
              </span>
            ) : d.fundamentals?.source ? (
              <span className={cn("text-[10px]", t.muted)}>
                {d.fundamentals.source}
                {d.fundamentals.as_of_date ? ` · ${d.fundamentals.as_of_date.slice(0, 10)}` : ""}
              </span>
            ) : null}
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5 sm:grid-cols-3 lg:grid-cols-4">
            {METRIC_ORDER.filter((k) => metrics[k.key] != null).map((k) => (
              <div key={k.key} className="flex flex-col">
                <dt className={t.label}>{k.label}</dt>
                <dd className={t.value}>{k.fmt(metrics[k.key] as number)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {/* NEW: Financials trend (5-yr) */}
      {trend.length >= 2 ? (
        <section className={t.card}>
          <div className={t.eyebrow}>
            Financials trend
            <span className={cn("text-[10px]", t.muted)}>
              {trend[0]?.period.slice(0, 4)}–{trend[trend.length - 1]?.period.slice(0, 4)}
              {d.statements?.currency ? ` · ${d.statements.currency}` : ""}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <TrendTile
              t={t}
              label="Revenue"
              values={trend.map((x) => x.revenue)}
              fmt={compact}
            />
            <TrendTile
              t={t}
              label="Net income"
              values={trend.map((x) => x.net_income)}
              fmt={compact}
            />
            <TrendTile
              t={t}
              label="Net margin"
              values={trend.map((x) => x.net_margin_pct)}
              fmt={(v) => `${v.toFixed(1)}%`}
            />
          </div>
        </section>
      ) : null}

      {/* NEW: Peer comparison */}
      {d.peers && Object.keys(d.peers.fields).length ? (
        <section className={t.card}>
          <div className={t.eyebrow}>
            Peer comparison
            <span className={cn("text-[10px]", t.muted)}>
              vs {d.peers.peers.join(", ")}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={cn("text-left", t.label)}>
                  <th className="py-1 pr-4 font-normal">Metric</th>
                  <th className="py-1 pr-4 font-normal">This</th>
                  <th className="py-1 pr-4 font-normal">Peer median</th>
                  <th className="py-1 pr-4 font-normal">Rank</th>
                  <th className="py-1 font-normal">Beats peers</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(d.peers.fields).map(([k, f]) => (
                  <tr key={k} className="border-t border-current/10">
                    <td className={cn("py-1.5 pr-4", t.muted)}>{PEER_LABELS[k] ?? k}</td>
                    <td className={cn("py-1.5 pr-4", t.value)}>{peerFmt(k, f.target)}</td>
                    <td className={cn("py-1.5 pr-4 font-mono tabular-nums", t.muted)}>
                      {f.peer_median != null ? peerFmt(k, f.peer_median) : "—"}
                    </td>
                    <td className={cn("py-1.5 pr-4 font-mono tabular-nums")}>
                      {f.rank != null ? `#${f.rank}/${f.n_peers + 1}` : "—"}
                    </td>
                    <td className="py-1.5">
                      {f.better_than_pct != null ? (
                        <div className="flex items-center gap-2">
                          <div className={cn("h-1.5 w-16 overflow-hidden rounded-full", t.barTrack)}>
                            <div
                              className={cn("h-full rounded-full", t.bar)}
                              style={{ width: `${f.better_than_pct}%` }}
                            />
                          </div>
                          <span className={cn("font-mono text-xs tabular-nums", t.muted)}>
                            {f.better_than_pct.toFixed(0)}%
                          </span>
                        </div>
                      ) : (
                        <span className={t.muted}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={cn("mt-3 text-[11px]", t.muted)}>{d.peers.disclaimer}</p>
        </section>
      ) : null}

      {/* Dossier */}
      <section className={t.card}>
        <Markdown>{d.dossier_markdown}</Markdown>
      </section>

      {/* Recent news */}
      {d.news?.length ? (
        <section className={t.card}>
          <div className={t.eyebrow}>Recent news ({d.news.length})</div>
          <ul className="space-y-1.5 text-sm">
            {d.news.slice(0, 8).map((n, i) => (
              <li key={i}>
                <a href={n.url} target="_blank" rel="noreferrer" className={t.link}>
                  {n.title}
                </a>{" "}
                <span className={cn("text-xs", t.muted)}>
                  · {n.source} · {n.time.slice(0, 10)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className={cn("text-[11px]", t.muted)}>{d.disclaimer}</p>
    </div>
  );
}

function Perf({ t, label, v }: { t: Theme; label: string; v: number | null | undefined }) {
  if (v == null) return <span className={t.muted}>{label} —</span>;
  const pos = v >= 0;
  return (
    <span className={pos ? t.pos : t.neg}>
      {label} {pos ? "+" : ""}
      {v}%
    </span>
  );
}

function TrendTile({
  t,
  label,
  values,
  fmt,
}: {
  t: Theme;
  label: string;
  values: (number | null)[];
  fmt: (v: number) => string;
}) {
  const nums = values.filter((v): v is number => v != null);
  const last = nums.length ? nums[nums.length - 1] : null;
  const first = nums.length ? nums[0] : null;
  const up = last != null && first != null ? last >= first : true;
  return (
    <div className="flex flex-col gap-1">
      <div className={t.label}>{label}</div>
      <div className="flex items-end justify-between gap-2">
        <span className={cn("text-lg", t.value)}>{last != null ? fmt(last) : "—"}</span>
        {nums.length >= 2 ? (
          <Sparkline values={nums} tone={up ? "up" : "down"} width={90} height={28} />
        ) : null}
      </div>
    </div>
  );
}
