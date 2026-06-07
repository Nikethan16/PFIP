"use client";

import * as React from "react";
import Link from "next/link";
import {
  LineChart as LineIcon,
  Plus,
  ScanSearch,
  Trash2,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAddWatchlist,
  useCandles,
  useRemoveWatchlist,
  useWatchlist,
} from "@/lib/api";
import { cn, formatIST, formatPct } from "@/lib/utils";
import { toast } from "@/components/ui/toast";
import { RegimeBadge } from "@/components/shared/regime-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import { Sparkline } from "@/components/charts/sparkline";
import type { WatchlistItem } from "@/lib/contracts";

type MarketGroup = "Crypto" | "US equity" | "India equity" | "FX" | "Other";

function groupOf(symbol: string): MarketGroup {
  const s = symbol.toUpperCase();
  if (
    /BTC|ETH|SOL|BNB|XRP|ADA|DOT|AVAX|LTC|DOGE|MATIC|LINK|UNI|SHIB|TRX|USDT|USDC|DAI/.test(
      s,
    )
  )
    return "Crypto";
  if (/NIFTY|SENSEX|\.NS$|\.BO$/.test(s)) return "India equity";
  if (/USD|EUR|GBP|JPY|INR/.test(s) && s.length <= 7) return "FX";
  if (/SPY|QQQ|DIA|VTI|VOO|IWM/.test(s) || /^[A-Z]{1,5}$/.test(s))
    return "US equity";
  return "Other";
}

export default function WatchlistPage() {
  const { data, isLoading, error } = useWatchlist();
  const add = useAddWatchlist();
  const remove = useRemoveWatchlist();

  const [openAdd, setOpenAdd] = React.useState(false);
  const [chartFor, setChartFor] = React.useState<string | null>(null);

  const onAdd = async (symbol: string, label?: string) => {
    try {
      const sym = symbol.trim().toUpperCase();
      await add.mutateAsync({
        symbol: sym,
        // The UI's free-text "label" maps to the backend `note` column.
        note: label?.trim() || undefined,
      });
      toast.success("Added to watchlist");
      setOpenAdd(false);
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const grouped = React.useMemo(() => {
    const map = new Map<MarketGroup, WatchlistItem[]>();
    (data ?? []).forEach((item) => {
      const g = groupOf(item.symbol);
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(item);
    });
    return map;
  }, [data]);

  /**
   * Market scope — `null` means show all. The chip strip below the page
   * header lets the user narrow to a single market.
   */
  const [scope, setScope] = React.useState<MarketGroup | null>(null);
  const visibleGroups = React.useMemo(() => {
    const entries = [...grouped.entries()];
    return scope ? entries.filter(([g]) => g === scope) : entries;
  }, [grouped, scope]);

  return (
    <div className="space-y-6">
      {/* Header — serif "Watchlist" editorial banner + add action. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Coverage // tracked symbols
            <FreshnessBadge sources={["yfinance_eod", "jugaad_eod"]} />
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Watchlist
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Symbols you&rsquo;re watching. Drives the morning brief + dashboard
            movers.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpenAdd(true)}
          className="inline-flex items-center gap-2 bg-primary px-4 py-2 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
        >
          <Plus className="h-3.5 w-3.5" />
          Add symbol
        </button>
      </div>

      {/* Market scope chips — empty / scope-all when data hasn't loaded yet. */}
      {data && data.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          <ScopeChip
            label={`All · ${data.length}`}
            active={scope === null}
            onClick={() => setScope(null)}
          />
          {[...grouped.entries()].map(([g, items]) => (
            <ScopeChip
              key={g}
              label={`${g} · ${items.length}`}
              active={scope === g}
              onClick={() => setScope(g)}
            />
          ))}
        </div>
      ) : null}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load watchlist: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <section className="border border-border/60 bg-card p-6">
          <EmptyState
            title="No items yet"
            description="Add the tickers you trade or research — we'll surface the live price, 24h / 1W / 1M deltas and the current regime."
            action={{
              label: "Add your first symbol",
              onClick: () => setOpenAdd(true),
            }}
          />
        </section>
      ) : (
        <div className="space-y-6">
          {visibleGroups.map(([group, items]) => (
            <section
              key={group}
              className="border border-border/60 bg-card"
            >
              <div className="flex items-baseline justify-between border-b border-border/40 px-5 py-3">
                <h2 className="eyebrow text-foreground">{group}</h2>
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {items.length} symbol{items.length === 1 ? "" : "s"}
                </span>
              </div>
              {/* Column header — editorial ledger. Hidden on mobile. */}
              <div className="hidden grid-cols-12 gap-3 border-b border-border/30 px-5 py-2 sm:grid">
                <span className="eyebrow col-span-4 !text-[10px]">Symbol</span>
                <span className="eyebrow col-span-2 !text-[10px] text-right">
                  Last
                </span>
                <span className="eyebrow col-span-2 !text-[10px] text-right">
                  24h
                </span>
                <span className="eyebrow col-span-3 !text-[10px]">
                  30d trend
                </span>
                <span className="sr-only col-span-1">Actions</span>
              </div>
              <ul className="divide-y divide-border/40">
                {items.map((item) => (
                  <WatchlistRow
                    key={item.id ?? item.symbol}
                    item={item}
                    onChart={() => setChartFor(item.symbol)}
                    onRemove={() =>
                      item.id
                        ? remove.mutate(
                            { id: item.id },
                            {
                              onSuccess: () => toast.success("Removed"),
                              onError: (err) =>
                                toast.error((err as Error).message),
                            },
                          )
                        : undefined
                    }
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <AddDialog
        open={openAdd}
        onOpenChange={setOpenAdd}
        pending={add.isPending}
        onSubmit={onAdd}
      />
      <ChartDialog symbol={chartFor} onClose={() => setChartFor(null)} />
    </div>
  );
}

/**
 * One ledger row for a watched symbol. Surfaces the live `last_price` and
 * `change_pct_24h` returned by GET /watchlist, the regime badge when present,
 * a 30-day sparkline + 1W/1M deltas derived from candles, and the chart /
 * remove actions.
 */
function WatchlistRow({
  item,
  onChart,
  onRemove,
}: {
  item: WatchlistItem;
  onChart: () => void;
  onRemove: () => void;
}) {
  const change24 = item.change_pct_24h ?? null;
  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 30);
    return d.toISOString();
  }, []);
  const { data: candles } = useCandles({
    symbol: item.symbol,
    timeframe: "1d",
    since,
  });
  const closes = (candles ?? []).map((c) => c.close);
  const wkChange = (() => {
    if (closes.length < 8) return null;
    const first = closes[closes.length - 8] ?? 0;
    const last = closes[closes.length - 1] ?? 0;
    if (!first) return null;
    return ((last - first) / first) * 100;
  })();
  const moChange = (() => {
    if (closes.length < 2) return null;
    const first = closes[0] ?? 0;
    const last = closes[closes.length - 1] ?? 0;
    if (!first) return null;
    return ((last - first) / first) * 100;
  })();
  const positive24 = (change24 ?? 0) >= 0;
  const Trend24 = positive24 ? TrendingUp : TrendingDown;
  const tone24 =
    change24 == null
      ? "text-muted-foreground"
      : positive24
        ? "text-emerald-700 dark:text-emerald-400"
        : "text-red-700 dark:text-red-400";

  return (
    <li className="grid grid-cols-12 items-center gap-3 px-5 py-3 hover-tile">
      {/* Symbol + note + regime */}
      <div className="col-span-12 min-w-0 sm:col-span-4">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-sm font-semibold tracking-tight">
            {item.symbol}
          </span>
          {item.regime ? <RegimeBadge regime={item.regime} /> : null}
        </div>
        {item.note ? (
          <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {item.note}
          </div>
        ) : null}
      </div>

      {/* Last price */}
      <div className="col-span-4 text-left sm:col-span-2 sm:text-right">
        <span className="font-label text-[9px] uppercase tracking-wider text-muted-foreground sm:hidden">
          Last
        </span>
        <div className="font-mono text-sm font-semibold tabular-nums">
          {item.last_price != null ? item.last_price.toLocaleString() : "—"}
        </div>
      </div>

      {/* 24h change */}
      <div className="col-span-4 text-left sm:col-span-2 sm:text-right">
        <span className="font-label text-[9px] uppercase tracking-wider text-muted-foreground sm:hidden">
          24h
        </span>
        <div
          className={cn(
            "flex items-center gap-1 font-mono text-sm font-semibold tabular-nums sm:justify-end",
            tone24,
          )}
        >
          {change24 != null ? (
            <>
              <Trend24 className="h-3 w-3" />
              {formatPct(change24)}
            </>
          ) : (
            "—"
          )}
        </div>
      </div>

      {/* 30d sparkline + 1W/1M deltas */}
      <div className="col-span-8 flex items-center gap-3 sm:col-span-3">
        <Sparkline values={closes} width={80} height={26} ariaLabel={`${item.symbol} 30d`} />
        <div className="flex gap-2 font-mono text-[10px] tabular-nums">
          <Delta label="1W" value={wkChange} />
          <Delta label="1M" value={moChange} />
        </div>
      </div>

      {/* Actions */}
      <div className="col-span-4 flex items-center justify-end gap-0.5 sm:col-span-1">
        <Button
          asChild
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={`Research ${item.symbol}`}
          title="Due-diligence dossier"
        >
          <Link href={`/diligence?symbol=${encodeURIComponent(item.symbol)}` as never}>
            <ScanSearch className="h-3.5 w-3.5" />
          </Link>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={onChart}
          aria-label={`Quick chart for ${item.symbol}`}
          title="Quick chart"
        >
          <LineIcon className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
          aria-label={`Remove ${item.symbol}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </li>
  );
}

function Delta({ label, value }: { label: string; value: number | null }) {
  const tone =
    value == null
      ? "text-muted-foreground"
      : value >= 0
        ? "text-emerald-700 dark:text-emerald-400"
        : "text-red-700 dark:text-red-400";
  return (
    <span className="inline-flex flex-col items-center leading-tight">
      <span className="font-label text-[8px] uppercase tracking-wider text-muted-foreground/80">
        {label}
      </span>
      <span className={cn("font-medium", tone)}>
        {value == null ? "—" : formatPct(value)}
      </span>
    </span>
  );
}

function AddDialog({
  open,
  onOpenChange,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  pending: boolean;
  onSubmit: (symbol: string, label?: string) => void;
}) {
  const [symbol, setSymbol] = React.useState("");
  const [label, setLabel] = React.useState("");

  React.useEffect(() => {
    if (!open) {
      setSymbol("");
      setLabel("");
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-serif text-xl tracking-tight">
            Add symbol
          </DialogTitle>
          <DialogDescription>
            Canonical ticker: BTC-USD, RELIANCE.NS, SPY, USDINR, …
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!symbol.trim()) return;
            onSubmit(symbol, label);
          }}
          className="space-y-3"
        >
          <div>
            <Label htmlFor="symbol" className="eyebrow">
              Symbol
            </Label>
            <Input
              id="symbol"
              placeholder="BTC-USD"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              autoFocus
              list="pfip-symbol-suggestions"
              className="mt-1 font-mono"
            />
            <datalist id="pfip-symbol-suggestions">
              <option value="BTC-USD" />
              <option value="ETH-USD" />
              <option value="SOL-USD" />
              <option value="SPY" />
              <option value="QQQ" />
              <option value="NIFTY50" />
              <option value="RELIANCE.NS" />
              <option value="USDINR" />
              <option value="EURUSD" />
            </datalist>
          </div>
          <div>
            <Label htmlFor="label" className="eyebrow">
              Label (optional)
            </Label>
            <Input
              id="label"
              placeholder="Core position"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="mt-1"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !symbol.trim()}>
              {pending ? "Adding…" : "Add"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ChartDialog({
  symbol,
  onClose,
}: {
  symbol: string | null;
  onClose: () => void;
}) {
  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 90);
    return d.toISOString();
  }, []);
  const { data, isLoading } = useCandles({
    symbol: symbol ?? "",
    timeframe: "1d",
    since,
  });
  if (!symbol) return null;
  return (
    <Dialog open onOpenChange={(o) => (!o ? onClose() : null)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-mono">{symbol}</DialogTitle>
          <DialogDescription>90-day close</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <Skeleton className="h-60 w-full" />
        ) : !data?.length ? (
          <EmptyState title="No data" />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data}>
              <XAxis
                dataKey="time"
                tickFormatter={(v: string) => formatIST(v, "dd MMM")}
                fontSize={11}
                minTickGap={24}
              />
              <YAxis fontSize={11} domain={["auto", "auto"]} width={48} />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--popover))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                labelFormatter={(v) => formatIST(String(v))}
              />
              <Line
                type="monotone"
                dataKey="close"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Market-scope filter pill. Active = amber primary tint, inactive = subtle
 * warm muted with hover lift. Square-cornered to match the Sahara chrome.
 */
function ScopeChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "border px-3 py-1 font-label text-[11px] uppercase tracking-wider transition-colors",
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border/70 text-muted-foreground hover:bg-accent/40 hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}
