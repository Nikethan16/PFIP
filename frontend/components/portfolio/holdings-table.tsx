"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Search, X } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Holding, HoldingCategory } from "@/lib/contracts";
import { formatINR, formatPct } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { assetClassLabel, holdingDisplayName } from "./holding-labels";

/**
 * Per-holding derived metrics computed by the page from the live marking
 * payload. Keeps this table presentational: the page owns "where the price
 * came from", the table just renders it.
 */
export interface HoldingMetrics {
  /** Live mark price per unit (INR), or cost-basis-derived per unit when unmarked. */
  pricePerUnitInr: number | null;
  /** Average cost per unit (INR) = cost_basis_inr / qty. */
  avgCostInr: number | null;
  /** Total market value (INR) = pricePerUnit × qty (cost basis when unmarked). */
  marketValueInr: number | null;
  /** Unrealised P&L (INR) = marketValue − cost basis. Null when unmarked. */
  pnlInr: number | null;
  /** Unrealised P&L (%). Null when unmarked or cost basis is 0. */
  pnlPct: number | null;
  /** True when a live mark price backs this row (vs cost-basis fallback). */
  marked: boolean;
}

interface HoldingsTableProps {
  holdings: Holding[];
  /** Derived MTM metrics, keyed by holding id. */
  metrics: Map<string, HoldingMetrics>;
  /** Currently selected holding id (amber left-stripe). */
  selectedId?: string | null;
  /** Row click → select this holding into the deep-dive panel. */
  onSelect?: (holding: Holding) => void;
}

type SortKey =
  | "symbol"
  | "category"
  | "price"
  | "avg_cost"
  | "pnl";

const ALL_CATEGORIES: HoldingCategory[] = [
  "equity",
  "etf",
  "mutual_fund",
  "ppf",
  "epf",
  "nps",
  "fd",
  "sgb",
  "gsec",
  "bond",
  "crypto_exchange",
  "crypto_self_custody",
  "cash",
];

/**
 * Editorial holdings table (Sahara split-pane left rail).
 *
 * Columns: SYMBOL (bold ticker + muted name) · ASSET CLASS · PRICE (live MTM) ·
 * AVG COST · P&L (signed, green/red). Rows are clickable to SELECT a holding;
 * the selected row gets an amber left-accent stripe. Search by symbol/ISIN/
 * broker + category filter pills + sortable columns are preserved.
 *
 * Mobile: rows stack into cards; filters stay on top.
 */
export function HoldingsTable({
  holdings,
  metrics,
  selectedId,
  onSelect,
}: HoldingsTableProps) {
  const [sortKey, setSortKey] = React.useState<SortKey>("pnl");
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("desc");
  const [activeCats, setActiveCats] = React.useState<Set<HoldingCategory>>(
    new Set(),
  );
  const [query, setQuery] = React.useState("");

  const categoriesPresent = React.useMemo(() => {
    const s = new Set<HoldingCategory>();
    holdings.forEach((h) => s.add(h.category));
    return ALL_CATEGORIES.filter((c) => s.has(c));
  }, [holdings]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return holdings.filter((h) => {
      if (activeCats.size && !activeCats.has(h.category)) return false;
      if (!q) return true;
      return (
        (h.symbol ?? "").toLowerCase().includes(q) ||
        (h.isin ?? "").toLowerCase().includes(q) ||
        (h.broker ?? "").toLowerCase().includes(q) ||
        (h.notes ?? "").toLowerCase().includes(q)
      );
    });
  }, [holdings, activeCats, query]);

  const sorted = React.useMemo(() => {
    const list = [...filtered];
    const getter: (h: Holding) => string | number | null | undefined = (h) => {
      const m = metrics.get(h.id);
      switch (sortKey) {
        case "symbol":
          return h.symbol ?? h.isin ?? "";
        case "category":
          return h.category;
        case "price":
          return m?.marketValueInr ?? 0;
        case "avg_cost":
          return m?.avgCostInr ?? 0;
        case "pnl":
          return m?.pnlInr ?? 0;
      }
    };
    list.sort((a, b) => {
      const va = getter(a);
      const vb = getter(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string" && typeof vb === "string") {
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      return sortDir === "asc"
        ? (va as number) - (vb as number)
        : (vb as number) - (va as number);
    });
    return list;
  }, [filtered, sortKey, sortDir, metrics]);

  const toggleCat = (c: HoldingCategory) => {
    setActiveCats((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  if (!holdings.length) {
    return (
      <EmptyState
        title="No holdings yet"
        description="Import CSVs from Zerodha / INDmoney / WazirX / CoinDCX on the Tax page to populate this view."
        action={{ label: "Go to tax imports", href: "/tax" }}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Search + filter pills */}
      <div className="flex flex-col gap-2 border-b border-border/40 p-4 sm:flex-row sm:items-center">
        <div className="relative w-full sm:max-w-xs">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search symbol, ISIN, broker…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-7"
            aria-label="Search holdings"
          />
          {query ? (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1">
          {categoriesPresent.map((c) => {
            const active = activeCats.has(c);
            return (
              <button
                key={c}
                type="button"
                onClick={() => toggleCat(c)}
                aria-pressed={active}
                className={cn(
                  "border px-2 py-0.5 font-label text-[10px] uppercase tracking-wider transition-colors",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border/60 bg-background hover:bg-accent",
                )}
              >
                {assetClassLabel(c)}
              </button>
            );
          })}
          {activeCats.size ? (
            <button
              type="button"
              onClick={() => setActiveCats(new Set())}
              className="font-label text-[10px] uppercase tracking-wider text-muted-foreground hover:underline"
            >
              Clear
            </button>
          ) : null}
        </div>
      </div>

      {/* Desktop table */}
      <div className="hidden flex-1 overflow-auto md:block">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow className="border-border/60 hover:bg-transparent">
              <SortHeader
                label="Symbol"
                k="symbol"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
              />
              <SortHeader
                label="Asset class"
                k="category"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
              />
              <SortHeader
                label="Price"
                k="price"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <SortHeader
                label="Avg cost"
                k="avg_cost"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <SortHeader
                label="P&L"
                k="pnl"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="text-center text-sm text-muted-foreground"
                >
                  No holdings match your filter.
                </TableCell>
              </TableRow>
            ) : (
              sorted.map((h) => {
                const m = metrics.get(h.id);
                const selected = selectedId === h.id;
                const pnl = m?.pnlInr ?? null;
                const positive = (pnl ?? 0) >= 0;
                return (
                  <TableRow
                    key={h.id}
                    onClick={() => onSelect?.(h)}
                    aria-selected={selected}
                    className={cn(
                      "cursor-pointer border-border/30 transition-colors",
                      selected
                        ? "bg-primary/5 hover:bg-primary/10"
                        : "hover:bg-accent/40",
                    )}
                  >
                    <TableCell
                      className={cn(
                        "border-l-2",
                        selected ? "border-l-primary" : "border-l-transparent",
                      )}
                    >
                      <div className="flex flex-col">
                        <span className="font-semibold">
                          {h.symbol ?? h.isin ?? "—"}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {holdingDisplayName(h)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="font-label text-xs uppercase tracking-wide text-muted-foreground">
                      {assetClassLabel(h.category)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {m?.pricePerUnitInr != null
                        ? formatINR(m.pricePerUnitInr, 2)
                        : "—"}
                      {m && !m.marked ? (
                        <div
                          className="font-label text-[10px] uppercase tracking-wide text-amber-600 dark:text-amber-400"
                          title="No live mark — showing cost basis"
                        >
                          at cost
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {m?.avgCostInr != null
                        ? formatINR(m.avgCostInr, 2)
                        : "—"}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono font-semibold tabular-nums",
                        pnl == null
                          ? "text-muted-foreground"
                          : positive
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-red-700 dark:text-red-400",
                      )}
                    >
                      {pnl != null
                        ? `${pnl >= 0 ? "+" : ""}${formatINR(pnl)}`
                        : "—"}
                      {m?.pnlPct != null ? (
                        <div className="text-[11px] font-normal">
                          {formatPct(m.pnlPct)}
                        </div>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Mobile cards */}
      <div className="grid flex-1 gap-3 overflow-auto p-4 md:hidden">
        {sorted.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            No holdings match your filter.
          </div>
        ) : (
          sorted.map((h) => {
            const m = metrics.get(h.id);
            const selected = selectedId === h.id;
            const pnl = m?.pnlInr ?? null;
            const positive = (pnl ?? 0) >= 0;
            return (
              <button
                key={h.id}
                type="button"
                onClick={() => onSelect?.(h)}
                aria-pressed={selected}
                className={cn(
                  "border bg-card p-4 text-left text-card-foreground transition-colors",
                  selected
                    ? "border-l-2 border-l-primary bg-primary/5"
                    : "hover:bg-accent/40",
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="font-semibold">
                      {h.symbol ?? h.isin ?? "—"}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {holdingDisplayName(h)}
                    </span>
                  </div>
                  <span className="font-label text-[10px] uppercase tracking-wide text-muted-foreground">
                    {assetClassLabel(h.category)}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
                  <div>
                    <div className="eyebrow">Price</div>
                    <div className="font-mono tabular-nums">
                      {m?.pricePerUnitInr != null
                        ? formatINR(m.pricePerUnitInr, 2)
                        : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="eyebrow">Avg cost</div>
                    <div className="font-mono tabular-nums">
                      {m?.avgCostInr != null ? formatINR(m.avgCostInr, 2) : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="eyebrow">P&amp;L</div>
                    <div
                      className={cn(
                        "font-mono font-semibold tabular-nums",
                        pnl == null
                          ? "text-muted-foreground"
                          : positive
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-red-700 dark:text-red-400",
                      )}
                    >
                      {pnl != null
                        ? `${pnl >= 0 ? "+" : ""}${formatINR(pnl)}`
                        : "—"}
                    </div>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function SortHeader({
  label,
  k,
  sortKey,
  dir,
  onClick,
  align = "left",
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  dir: "asc" | "desc";
  onClick: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === k;
  const Icon = active ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <TableHead
      className={align === "right" ? "text-right" : undefined}
      aria-sort={
        active ? (dir === "asc" ? "ascending" : "descending") : "none"
      }
    >
      <button
        type="button"
        onClick={() => onClick(k)}
        className={cn(
          "inline-flex items-center gap-1 font-label text-[11px] uppercase tracking-wider",
          align === "right" && "flex-row-reverse",
          active ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {label}
        <Icon className="h-3 w-3" />
      </button>
    </TableHead>
  );
}
