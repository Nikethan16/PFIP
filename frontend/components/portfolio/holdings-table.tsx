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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Holding, HoldingCategory } from "@/lib/contracts";
import { formatINR, formatPct } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";

interface HoldingsTableProps {
  holdings: Holding[];
  /** Called when the user clicks "Close" on a row. Triggers the close flow. */
  onClosePosition?: (holding: Holding) => void;
  /** Id of the holding whose close is currently in flight (disables its button). */
  closingHoldingId?: string | null;
}

type SortKey =
  | "symbol"
  | "category"
  | "qty"
  | "cost_basis_inr"
  | "market_value_inr"
  | "unrealized_pnl_inr"
  | "unrealized_pnl_pct";

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
 * Holdings table with sortable columns, category filter pills, search by
 * symbol/ISIN, and a per-row "close" action that calls `onClosePosition`.
 *
 * Mobile: rows stack into cards; filter pills + search stay at the top.
 */
export function HoldingsTable({
  holdings,
  onClosePosition,
  closingHoldingId,
}: HoldingsTableProps) {
  const [sortKey, setSortKey] = React.useState<SortKey>("market_value_inr");
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
      switch (sortKey) {
        case "symbol":
          return h.symbol ?? h.isin ?? "";
        case "category":
          return h.category;
        case "qty":
          return h.qty;
        case "cost_basis_inr":
          return h.cost_basis_inr;
        case "market_value_inr":
          return h.market_value_inr ?? 0;
        case "unrealized_pnl_inr":
          return h.unrealized_pnl_inr ?? 0;
        case "unrealized_pnl_pct":
          return h.unrealized_pnl_pct ?? 0;
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
  }, [filtered, sortKey, sortDir]);

  const toggleCat = (c: HoldingCategory) => {
    setActiveCats((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key)
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
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
    <div className="space-y-3">
      {/* Search + filter pills */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
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
                  "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                  active
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background hover:bg-accent",
                )}
              >
                {c}
              </button>
            );
          })}
          {activeCats.size ? (
            <button
              type="button"
              onClick={() => setActiveCats(new Set())}
              className="text-[11px] text-muted-foreground hover:underline"
            >
              Clear
            </button>
          ) : null}
        </div>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <SortHeader
                label="Asset"
                k="symbol"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
              />
              <SortHeader
                label="Category"
                k="category"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
              />
              <SortHeader
                label="Qty"
                k="qty"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <SortHeader
                label="Cost basis"
                k="cost_basis_inr"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <SortHeader
                label="Market value"
                k="market_value_inr"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <SortHeader
                label="Unrealised P&L"
                k="unrealized_pnl_inr"
                sortKey={sortKey}
                dir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <TableHead className="w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground">
                  No holdings match your filter.
                </TableCell>
              </TableRow>
            ) : (
              sorted.map((h) => (
                <TableRow key={h.id}>
                  <TableCell className="font-medium">
                    {h.symbol ?? h.isin ?? "—"}
                    {h.broker ? (
                      <div className="text-xs text-muted-foreground">
                        {h.broker}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{h.category}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {h.qty}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatINR(h.cost_basis_inr)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatINR(h.market_value_inr)}
                  </TableCell>
                  <TableCell
                    className={`text-right tabular-nums ${
                      (h.unrealized_pnl_inr ?? 0) >= 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {formatINR(h.unrealized_pnl_inr)}
                    {h.unrealized_pnl_pct != null ? (
                      <div className="text-xs">
                        {formatPct(h.unrealized_pnl_pct)}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right">
                    {onClosePosition && !h.closed_at ? (
                      // Closing the holding creates a linked post-mortem journal
                      // stub server-side and returns its id, which the page
                      // wiring uses to open the post-mortem dialog.
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={closingHoldingId === h.id}
                        onClick={() => onClosePosition(h)}
                        title="Close this position and start its post-mortem"
                      >
                        {closingHoldingId === h.id ? "Closing…" : "Close"}
                      </Button>
                    ) : h.closed_at ? (
                      <Badge variant="secondary" className="text-[10px]">
                        Closed
                      </Badge>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Mobile cards */}
      <div className="grid gap-3 md:hidden">
        {sorted.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            No holdings match your filter.
          </div>
        ) : (
          sorted.map((h) => {
            const positive = (h.unrealized_pnl_inr ?? 0) >= 0;
            return (
              <div
                key={h.id}
                className="rounded-lg border bg-card p-4 text-card-foreground shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium">{h.symbol ?? h.isin ?? "—"}</div>
                  <Badge variant="outline">{h.category}</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <div className="text-xs text-muted-foreground">Qty</div>
                    <div className="tabular-nums">{h.qty}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Cost</div>
                    <div className="tabular-nums">
                      {formatINR(h.cost_basis_inr)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Value</div>
                    <div className="tabular-nums">
                      {formatINR(h.market_value_inr)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">P&amp;L</div>
                    <div
                      className={`tabular-nums ${
                        positive
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-red-600 dark:text-red-400"
                      }`}
                    >
                      {formatINR(h.unrealized_pnl_inr)}
                    </div>
                  </div>
                </div>
                {onClosePosition && !h.closed_at ? (
                  // See the desktop branch above: close creates the post-mortem
                  // stub and returns its journal id.
                  <div className="mt-3 flex justify-end">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={closingHoldingId === h.id}
                      onClick={() => onClosePosition(h)}
                      title="Close this position and start its post-mortem"
                    >
                      {closingHoldingId === h.id ? "Closing…" : "Close"}
                    </Button>
                  </div>
                ) : null}
              </div>
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
    <TableHead className={align === "right" ? "text-right" : undefined}>
      <button
        type="button"
        onClick={() => onClick(k)}
        className={cn(
          "inline-flex items-center gap-1 text-xs font-medium",
          align === "right" && "flex-row-reverse",
          active ? "text-foreground" : "text-muted-foreground",
        )}
        aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      >
        {label}
        <Icon className="h-3 w-3" />
      </button>
    </TableHead>
  );
}
