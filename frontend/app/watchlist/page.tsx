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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Watchlist</h1>
          <p className="text-sm text-muted-foreground">
            Symbols you&apos;re watching. Drives the morning brief + dashboard
            movers.
          </p>
        </div>
        <Button onClick={() => setOpenAdd(true)} className="gap-2">
          <Plus className="h-4 w-4" /> Add symbol
        </Button>
      </div>

      <div>
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
            action={{ label: "Add your first symbol", onClick: () => setOpenAdd(true) }}
          />
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {data.map((item) => {
              const change24 = item.change_pct_24h ?? 0;
              return (
                <li
                  key={item.id}
                  className="flex items-start justify-between rounded-md border bg-card p-3"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{item.symbol}</span>
                      {item.regime ? (
                        <RegimeBadge regime={item.regime} />
                      ) : null}
                    </div>
                    {item.label ? (
                      <div className="text-xs text-muted-foreground">
                        {item.label}
                      </div>
                    ) : null}
                    <div className="flex items-center gap-3 text-xs">
                      <span
                        className={cn(
                          "tabular-nums",
                          change24 >= 0
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-red-600 dark:text-red-400",
                        )}
                      >
                        24h {formatPct(change24)}
                      </span>
                      <WeeklyDelta symbol={item.symbol} />
                    </div>
                    {item.last_price != null ? (
                      <div className="text-xs tabular-nums">
                        last{" "}
                        <span className="font-medium">
                          {item.last_price.toLocaleString()}
                        </span>
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setChartFor(item.symbol)}
                      aria-label={`Quick chart for ${item.symbol}`}
                      title="Quick chart"
                    >
                      <LineIcon className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() =>
                        remove.mutate(
                          { id: item.id },
                          {
                            onSuccess: () => toast.success("Removed"),
                            onError: (err) =>
                              toast.error((err as Error).message),
                          },
                        )
                      }
                      aria-label={`Remove ${item.symbol}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <AddDialog
        open={openAdd}
        onOpenChange={setOpenAdd}
        pending={add.isPending}
        onSubmit={onAdd}
      />
      <ChartDialog
        symbol={chartFor}
        onClose={() => setChartFor(null)}
      />
    </div>
  );
}

function WeeklyDelta({ symbol }: { symbol: string }) {
  const since = React.useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 8);
    return d.toISOString();
  }, []);
  const { data } = useCandles({ symbol, timeframe: "1d", since });
  if (!data || data.length < 2) return <span>—</span>;
  const first = data[0].close;
  const last = data[data.length - 1].close;
  const ch = ((last - first) / first) * 100;
  return (
    <span
      className={cn(
        "tabular-nums",
        ch >= 0
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-red-600 dark:text-red-400",
      )}
    >
      1W {formatPct(ch)}
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
            {/* TODO(user): add an autocomplete source — we can plug
                in a search endpoint later, e.g. `/assets/search?q=…` */}
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
              <option value="SPY" />
              <option value="QQQ" />
              <option value="NIFTY50" />
              <option value="RELIANCE.NS" />
              <option value="USDINR" />
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
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
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
          <DialogTitle>{symbol}</DialogTitle>
          <DialogDescription>90d close</DialogDescription>
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
