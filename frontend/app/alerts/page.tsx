"use client";

/**
 * Alerts (D2) — define price / % rules and live-check them against the latest
 * stored prices. Rules persist locally (single-user). Background firing to the
 * bell + Telegram is a separate, server-side setting (logged follow-up); this
 * page is the define + on-demand-check surface.
 */

import * as React from "react";
import { BellRing, Check, Plus, RefreshCw, Trash2, X } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useAlertKinds,
  useEvaluateAlerts,
  type AlertEval,
  type AlertRule,
  type AlertRuleKind,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "pfip.alertRules.v1";

const KIND_LABEL: Record<AlertRuleKind, string> = {
  price_above: "Price above",
  price_below: "Price below",
  pct_up_1d: "Up ≥ (1d %)",
  pct_down_1d: "Down ≥ (1d %)",
};

function loadRules(): AlertRule[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export default function AlertsPage() {
  useAlertKinds(); // warms the kinds cache; labels are local for instant render
  const evaluate = useEvaluateAlerts();

  const [rules, setRules] = React.useState<AlertRule[]>([]);
  React.useEffect(() => setRules(loadRules()), []);

  const persist = (next: AlertRule[]) => {
    setRules(next);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const [draft, setDraft] = React.useState<AlertRule>({
    symbol: "",
    kind: "price_above",
    threshold: 0,
  });

  const addRule = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.symbol.trim()) return;
    persist([
      ...rules,
      { ...draft, id: newId(), symbol: draft.symbol.trim().toUpperCase() },
    ]);
    setDraft({ symbol: "", kind: "price_above", threshold: 0 });
  };

  const resultByRuleId = React.useMemo(() => {
    const map = new Map<string, AlertEval>();
    (evaluate.data?.results ?? []).forEach((r) => {
      if (r.rule.id) map.set(r.rule.id, r);
    });
    return map;
  }, [evaluate.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        description="Define price and movement rules, then check them against the latest prices. Informational — not trade instructions."
      />

      {/* New rule */}
      <form
        onSubmit={addRule}
        className="flex flex-wrap items-end gap-2 border border-border/60 bg-card p-5"
      >
        <div>
          <label className="eyebrow mb-1 block">Symbol</label>
          <Input
            value={draft.symbol}
            onChange={(e) => setDraft((d) => ({ ...d, symbol: e.target.value }))}
            placeholder="e.g. AAPL or RELIANCE.NS"
            className="w-48"
          />
        </div>
        <div>
          <label className="eyebrow mb-1 block">Condition</label>
          <Select
            value={draft.kind}
            onValueChange={(v) => setDraft((d) => ({ ...d, kind: v as AlertRuleKind }))}
          >
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(KIND_LABEL) as AlertRuleKind[]).map((k) => (
                <SelectItem key={k} value={k}>
                  {KIND_LABEL[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="eyebrow mb-1 block">
            {draft.kind.startsWith("pct") ? "Percent" : "Price"}
          </label>
          <Input
            inputMode="decimal"
            value={String(draft.threshold)}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                threshold: Number(e.target.value.replace(/,/g, "")) || 0,
              }))
            }
            className="w-28"
          />
        </div>
        <Button type="submit" size="sm" className="gap-1">
          <Plus className="h-3.5 w-3.5" /> Add alert
        </Button>
      </form>

      {/* Rules + check */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-serif text-xl tracking-tight">
          {rules.length} alert{rules.length === 1 ? "" : "s"}
        </h2>
        <div className="flex items-center gap-2">
          {evaluate.data ? (
            <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
              {evaluate.data.n_triggered} triggered
            </span>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            disabled={!rules.length || evaluate.isPending}
            onClick={() => evaluate.mutate({ rules })}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", evaluate.isPending && "animate-spin")} />
            Check now
          </Button>
        </div>
      </div>

      {evaluate.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(evaluate.error as Error).message}
        </div>
      ) : null}

      {rules.length === 0 ? (
        <div className="flex flex-col items-center gap-2 border border-dashed border-border/60 bg-card px-6 py-12 text-center">
          <BellRing className="h-6 w-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No alerts yet. Add a price or movement rule above.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {rules.map((r) => {
            const res = r.id ? resultByRuleId.get(r.id) : undefined;
            return (
              <li
                key={r.id}
                className={cn(
                  "flex flex-wrap items-center justify-between gap-3 border p-4",
                  res?.triggered
                    ? "border-emerald-600/40 bg-emerald-500/5"
                    : "border-border/60 bg-card",
                )}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{r.symbol}</span>
                    <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                      {KIND_LABEL[r.kind]} {r.threshold}
                      {r.kind.startsWith("pct") ? "%" : ""}
                    </span>
                  </div>
                  {res ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {res.observed} · {res.reason}
                    </p>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  {res ? (
                    res.triggered ? (
                      <span className="inline-flex items-center gap-1 font-label text-[10px] uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                        <Check className="h-3.5 w-3.5" /> Triggered
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                        <X className="h-3.5 w-3.5" /> Not yet
                      </span>
                    )
                  ) : null}
                  <button
                    type="button"
                    aria-label="Delete alert"
                    onClick={() => persist(rules.filter((x) => x.id !== r.id))}
                    className="border border-border p-1.5 text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {evaluate.data?.disclaimer ? (
        <p className="text-[11px] text-muted-foreground">{evaluate.data.disclaimer}</p>
      ) : null}
    </div>
  );
}
