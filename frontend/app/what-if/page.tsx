"use client";

/**
 * What-If — simulate a trade before you place it.
 *
 * Enter a proposed BUY/SELL and see the impact on exposure, concentration
 * (HHI), book value, and — for a SELL — the Indian capital-gains tax it would
 * realise. Data: useWhatIf() → POST /portfolio/what-if. Nothing is executed.
 */

import * as React from "react";
import { GitCompareArrows, Scale } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWhatIf, type WhatIfResult } from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";

export default function WhatIfPage() {
  const [action, setAction] = React.useState<"BUY" | "SELL">("BUY");
  const [symbol, setSymbol] = React.useState("");
  const [qty, setQty] = React.useState("");
  const [price, setPrice] = React.useState("");
  const mutation = useWhatIf();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = Number(qty);
    const p = Number(price);
    if (!symbol || !(q > 0) || !(p > 0)) return;
    mutation.mutate({ action, symbol: symbol.trim(), qty: q, price: p });
  }

  const res = mutation.data;

  return (
    <div className="space-y-6">
      <div className="page-header">
        <div className="eyebrow">Pre-trade // simulation</div>
        <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
          What-If
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Test a trade against your live book before you place it — see how
          exposure, concentration, and tax move. Advisory only; nothing executes.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="grid grid-cols-2 gap-4 border border-border/60 bg-card p-5 sm:grid-cols-5"
      >
        <div className="flex flex-col gap-1.5">
          <Label className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            Action
          </Label>
          <Select value={action} onValueChange={(v) => setAction(v as "BUY" | "SELL")}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="BUY">BUY</SelectItem>
              <SelectItem value="SELL">SELL</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            Symbol
          </Label>
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="RELIANCE.NS"
            className="font-mono"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            Qty
          </Label>
          <Input
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            inputMode="decimal"
            placeholder="10"
            className="font-mono"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            Price (INR)
          </Label>
          <Input
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            inputMode="decimal"
            placeholder="1500"
            className="font-mono"
          />
        </div>
        <Button type="submit" disabled={mutation.isPending} className="self-end">
          {mutation.isPending ? "Simulating…" : "Simulate"}
        </Button>
      </form>

      {mutation.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(mutation.error as Error).message}
        </div>
      ) : !res ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={GitCompareArrows}
            title="Run a simulation"
            description="Enter a proposed trade above to see the before/after impact on your portfolio."
          />
        </section>
      ) : (
        <WhatIfResultView res={res} />
      )}
    </div>
  );
}

function WhatIfResultView({ res }: { res: WhatIfResult }) {
  const taxInr = typeof res.tax_impact.tax_inr === "number" ? res.tax_impact.tax_inr : null;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SnapshotCard title="Before" snap={res.before} />
        <SnapshotCard title="After" snap={res.after} accent />
      </div>

      <section className="border border-border/60 bg-card p-5">
        <div className="eyebrow flex items-center gap-1.5">
          <Scale className="h-3.5 w-3.5" /> Impact
        </div>
        <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Delta label="Book value" value={formatINR(res.deltas.total_value_inr)} positive={res.deltas.total_value_inr >= 0} />
          <Delta
            label="Concentration (HHI)"
            value={`${res.deltas.hhi >= 0 ? "+" : ""}${res.deltas.hhi.toFixed(4)}`}
            positive={res.deltas.hhi <= 0}
          />
          <Delta label="Positions" value={`${res.deltas.n_positions >= 0 ? "+" : ""}${res.deltas.n_positions}`} positive />
          {res.action === "SELL" && taxInr != null ? (
            <Delta label="Tax realised" value={formatINR(taxInr)} positive={false} />
          ) : null}
        </div>
        {res.disclaimer ? (
          <p className="mt-4 text-[11px] text-muted-foreground">{res.disclaimer}</p>
        ) : null}
      </section>
    </div>
  );
}

function SnapshotCard({
  title,
  snap,
  accent,
}: {
  title: string;
  snap: WhatIfResult["before"];
  accent?: boolean;
}) {
  return (
    <section className={cn("border bg-card p-5", accent ? "border-primary/40" : "border-border/60")}>
      <div className="eyebrow">{title}</div>
      <div className="mt-2 flex items-baseline justify-between">
        <span className="font-mono text-xl font-semibold tabular-nums">{formatINR(snap.total_value_inr)}</span>
        <span className="text-xs text-muted-foreground">{snap.n_positions} positions · HHI {snap.hhi.toFixed(3)}</span>
      </div>
      <div className="mt-3 space-y-1">
        {Object.entries(snap.exposure_by_category_inr)
          .sort((a, b) => b[1] - a[1])
          .map(([cat, v]) => (
            <div key={cat} className="flex items-baseline justify-between gap-2 text-xs">
              <span className="font-label uppercase tracking-wider text-muted-foreground">{cat}</span>
              <span className="font-mono tabular-nums">{formatINR(v)}</span>
            </div>
          ))}
      </div>
    </section>
  );
}

function Delta({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className="border border-border/50 bg-secondary/30 p-3">
      <div className="eyebrow">{label}</div>
      <div
        className={cn(
          "mt-0.5 font-mono text-base font-semibold tabular-nums",
          positive ? "text-emerald-600 dark:text-emerald-400" : "text-destructive",
        )}
      >
        {value}
      </div>
    </div>
  );
}
