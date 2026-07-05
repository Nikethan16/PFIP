"use client";

import * as React from "react";

import { usePeers } from "@/lib/api";
import { SectionCard } from "@/components/shared/section-card";
import { cn } from "@/lib/utils";

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
const ratio = (v: number) => v.toFixed(2);
const pct = (v: number) => `${(Math.abs(v) <= 1 ? v * 100 : v).toFixed(1)}%`;
const fmt = (k: string, v: number) =>
  ["pe_ratio", "pb_ratio", "debt_to_equity"].includes(k) ? ratio(v) : pct(v);

/**
 * Curated peer comparison for a symbol (GET /diligence/{sym}/peers). Renders
 * nothing when there's no peer group or no stored metrics, so it's safe to drop
 * onto any diligence/research surface.
 */
export function PeerTable({ symbol }: { symbol: string }) {
  const { data, isLoading } = usePeers(symbol);
  if (isLoading || !data || !Object.keys(data.fields ?? {}).length) return null;

  return (
    <SectionCard
      title="Peer comparison"
      actions={
        <span className="text-[10px] text-muted-foreground">vs {data.peers.join(", ")}</span>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left font-label text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="py-1 pr-4 font-normal">Metric</th>
              <th className="py-1 pr-4 font-normal">This</th>
              <th className="py-1 pr-4 font-normal">Peer median</th>
              <th className="py-1 pr-4 font-normal">Rank</th>
              <th className="py-1 font-normal">Beats peers</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.fields).map(([k, f]) => (
              <tr key={k} className="border-t border-border/40">
                <td className="py-1.5 pr-4 text-muted-foreground">{PEER_LABELS[k] ?? k}</td>
                <td className="py-1.5 pr-4 font-mono text-sm tabular-nums">{fmt(k, f.target)}</td>
                <td className="py-1.5 pr-4 font-mono tabular-nums text-muted-foreground">
                  {f.peer_median != null ? fmt(k, f.peer_median) : "—"}
                </td>
                <td className="py-1.5 pr-4 font-mono tabular-nums">
                  {f.rank != null ? `#${f.rank}/${f.n_peers + 1}` : "—"}
                </td>
                <td className="py-1.5">
                  {f.better_than_pct != null ? (
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-secondary">
                        <div
                          className={cn("h-full rounded-full bg-primary/70")}
                          style={{ width: `${f.better_than_pct}%` }}
                        />
                      </div>
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">
                        {f.better_than_pct.toFixed(0)}%
                      </span>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.disclaimer ? (
        <p className="mt-3 text-[11px] text-muted-foreground">{data.disclaimer}</p>
      ) : null}
    </SectionCard>
  );
}
