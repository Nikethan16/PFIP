"use client";

import * as React from "react";
import { LineChart as LineIcon, Plus, Trash2 } from "lucide-react";
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
import { PageHeader } from "@/components/shared/page-header";
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
      await add.mutateAsync({
        symbol: symbol.trim().toUpperCase(),
        label: label?.trim() || undefined,
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
   * header lets the user narrow to a single market (matches the Stitch
   * Watchlist spec from `docs/FRONTEND_DESIGN_PROMPT.md` §8.2).
   */
  const [scope, setScope] = React.useState<MarketGroup | null>(null);
  const visibleGroups = React.useMemo(() => {
    const entries = [...grouped.entries()];
    return scope ? entries.filter(([g]) => g === scope) : entries;
  }, [grouped, scope]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Watchlist"
        description="Symbols you’re watching. Drives the morning brief + dashboard movers."
        actions={
          <Button onClick={() => setOpenAdd(true)} size="sm" className="gap-2">
            <Plus className="h-3.5 w-3.5" /> Add symbol
          </Button>
        }
      />

      {/* Market scope chips — empty / scope-all when data hasn't loaded yet. */}
      {data && data.length > 0 ? (
        <div className="flex flex-wrap gap-1">
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
        <div className="grid gap-2 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load watchlist: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <EmptyState
          title="No items yet"
          description="Add the tickers you trade or research — we'll surface 24h + 1W deltas and the current regime."
          action={{
            label: "Add your first symbol",
            onClick: () => setOpenAdd(true),
          }}
        />
      ) : (
        <div className="space-y-6">
          {visibleGroups.map(([group, items]) => (
            <section key={group} className="space-y-2">
              <div className="flex items-baseline justify-between">
                <h2 className="eyebrow text-foreground">{group}</h2>
                <span className="text-[10px] text-muted-foreground">
                  {items.length} item{items.length === 1 ? "" : "s"}
                </span>
              </div>
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((item) => (
                  <WatchlistTile
                    key={item.id}
                    item={item}
                    onChart={() => setChartFor(item.symbol)}
                    onRemove={() =>
                      remove.mutate(
                        { id: item.id },
                        {
                          onSuccess: () => toast.success("Removed"),
                          onError: (err) =>
                            toast.error((err as Error).message),
                        },
                      )
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

function WatchlistTile({
  item,
  onChart,
  onRemove,
}: {
  item: WatchlistItem;
  onChart: () => void;
  onRemove: () => void;
}) {
  const change24 = item.change_pct_24h ?? 0;
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
  const positive24 = change24 >= 0;
  return (
    <li className="rounded-lg border bg-card p-3 transition-all hover:border-foreground/20 hover:shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-mono text-sm font-semibold">
              {item.symbol}
            </span>
            {item.regime ? <RegimeBadge regime={item.regime} /> : null}
          </div>
          {item.label ? (
            <div className="truncate text-[11px] text-muted-foreground">
              {item.label}
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-0.5">
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
      </div>

      <div className="mt-2 flex items-center gap-3">
        <Sparkline values={closes} width={88} height={30} />
        <div className="grid flex-1 grid-cols-3 gap-1.5 text-[11px]">
          <DeltaPill label="1D" value={change24} positive={positive24} />
          <DeltaPill label="1W" value={wkChange} />
          <DeltaPill label="1M" value={moChange} />
        </div>
      </div>

      {item.last_price != null ? (
        <div className="mt-2 flex items-center justify-between border-t pt-2">
          <span className="text-[10px] text-muted-foreground">Last</span>
          <span className="font-num text-xs font-semibold">
            {item.last_price.toLocaleString()}
          </span>
        </div>
      ) : null}
    </li>
  );
}

function DeltaPill({
  label,
  value,
  positive,
}: {
  label: string;
  value: number | null;
  positive?: boolean;
}) {
  const tone =
    value == null
      ? "text-muted-foreground"
      : (positive ?? value >= 0)
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-red-600 dark:text-red-400";
  return (
    <div className="rounded border bg-background px-1.5 py-1 text-center">
      <div className="text-[9px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={cn("font-num text-[11px] font-medium tabular-nums", tone)}>
        {value == null ? "—" : formatPct(value)}
      </div>
    </div>
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
          <DialogTitle>Add symbol</DialogTitle>
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
            <Label htmlFor="symbol">Symbol</Label>
            <Input
              id="symbol"
              placeholder="BTC-USD"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              autoFocus
              list="pfip-symbol-suggestions"
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
            <Label htmlFor="label">Label (optional)</Label>
            <Input
              id="label"
              placeholder="Core position"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
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
 * Tiny pill-button used by the market-scope row. Active = teal primary,
 * inactive = subtle muted with hover lift. Matches the Stitch filter
 * chip pattern.
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
        "rounded-full border px-3 py-1 text-[11px] font-medium transition-colors",
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}
