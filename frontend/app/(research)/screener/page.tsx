"use client";

/**
 * Screener (D4) — filter the stored-fundamentals universe by numeric criteria
 * (e.g. ROCE > 20 AND P/E < 25 AND D/E < 0.5). Saved screens persist locally.
 *
 * Coverage depends on what the nightly fundamentals ingest has stored, so an
 * empty result usually means "no tracked name has all those fields yet", not a
 * bug — the result echoes universe/evaluated counts to make that honest.
 */

import * as React from "react";
import { Filter, Plus, Save, Trash2, X } from "lucide-react";

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
  useRunScreen,
  useScreenerFields,
  type ScreenCriterion,
  type ScreenOp,
} from "@/lib/api";

const OP_LABELS: Record<ScreenOp, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
};

const STORAGE_KEY = "pfip.savedScreens.v1";

interface SavedScreen {
  name: string;
  criteria: ScreenCriterion[];
}

function loadSaved(): SavedScreen[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export default function ScreenerPage() {
  const fieldsQuery = useScreenerFields();
  const run = useRunScreen();
  const allFields = fieldsQuery.data?.fields ?? [];

  const [rows, setRows] = React.useState<ScreenCriterion[]>([
    { field: "roce", op: "gt", value: 20 },
  ]);
  const [saved, setSaved] = React.useState<SavedScreen[]>([]);
  React.useEffect(() => setSaved(loadSaved()), []);

  const label = React.useCallback(
    (key: string) => allFields.find((f) => f.key === key)?.label ?? key,
    [allFields],
  );

  const persist = (next: SavedScreen[]) => {
    setSaved(next);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const addRow = () =>
    setRows((r) => [
      ...r,
      { field: allFields[0]?.key ?? "pe_ratio", op: "lt", value: 25 },
    ]);

  const updateRow = (i: number, patch: Partial<ScreenCriterion>) =>
    setRows((r) => r.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  const removeRow = (i: number) =>
    setRows((r) => r.filter((_, idx) => idx !== i));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run.mutate({ criteria: rows });
  };

  const saveCurrent = () => {
    const name = window.prompt("Name this screen:");
    if (name?.trim()) persist([...saved, { name: name.trim(), criteria: rows }]);
  };

  const result = run.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Screener"
        description="Filter the stored-fundamentals universe by valuation and quality metrics. Coverage depends on the nightly ingest — a research aid, not advice."
      />

      <form onSubmit={submit} className="space-y-3 border border-border/60 bg-card p-5">
        {rows.map((row, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Select value={row.field} onValueChange={(v) => updateRow(i, { field: v })}>
              <SelectTrigger className="w-44">
                <SelectValue placeholder="Metric" />
              </SelectTrigger>
              <SelectContent>
                {allFields.map((f) => (
                  <SelectItem key={f.key} value={f.key}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={row.op}
              onValueChange={(v) => updateRow(i, { op: v as ScreenOp })}
            >
              <SelectTrigger className="w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(OP_LABELS) as ScreenOp[]).map((op) => (
                  <SelectItem key={op} value={op}>
                    {OP_LABELS[op]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              inputMode="decimal"
              value={String(row.value)}
              onChange={(e) =>
                updateRow(i, { value: Number(e.target.value.replace(/,/g, "")) || 0 })
              }
              className="w-28"
            />
            <button
              type="button"
              onClick={() => removeRow(i)}
              aria-label="Remove filter"
              className="border border-border p-2 text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button type="button" variant="outline" size="sm" className="gap-1" onClick={addRow}>
            <Plus className="h-3.5 w-3.5" /> Add filter
          </Button>
          <Button type="submit" size="sm" className="gap-1" disabled={run.isPending || !rows.length}>
            <Filter className="h-3.5 w-3.5" />
            {run.isPending ? "Screening…" : "Run screen"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1"
            onClick={saveCurrent}
            disabled={!rows.length}
          >
            <Save className="h-3.5 w-3.5" /> Save
          </Button>
        </div>
      </form>

      {saved.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="eyebrow">Saved</span>
          {saved.map((s, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 border border-border/60 bg-secondary/40 py-1 pl-2.5 pr-1 text-xs"
            >
              <button
                type="button"
                className="font-label uppercase tracking-wider hover:text-primary"
                onClick={() => setRows(s.criteria)}
              >
                {s.name}
              </button>
              <button
                type="button"
                aria-label={`Delete ${s.name}`}
                onClick={() => persist(saved.filter((_, idx) => idx !== i))}
                className="text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      ) : null}

      {run.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(run.error as Error).message}
        </div>
      ) : null}

      {result ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-serif text-xl tracking-tight">
              {result.matches.length} match{result.matches.length === 1 ? "" : "es"}
            </h2>
            <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
              {result.n_evaluated} of {result.n_universe} names had every filtered field
            </span>
          </div>
          {result.matches.length ? (
            <div className="overflow-x-auto border border-border/60">
              <table className="w-full text-sm">
                <thead className="bg-secondary/40">
                  <tr className="text-left">
                    <th className="px-3 py-2 font-label text-[10px] uppercase tracking-wider">
                      Symbol
                    </th>
                    {result.fields_returned.map((f) => (
                      <th
                        key={f}
                        className="px-3 py-2 text-right font-label text-[10px] uppercase tracking-wider"
                      >
                        {label(f)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.matches.map((m) => (
                    <tr key={m.symbol} className="border-t border-border/40">
                      <td className="px-3 py-2 font-medium">{m.symbol}</td>
                      {result.fields_returned.map((f) => (
                        <td
                          key={f}
                          className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground"
                        >
                          {m.metrics[f] !== undefined ? m.metrics[f].toFixed(2) : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="border border-border/60 bg-card p-4 text-sm text-muted-foreground">
              No names matched. Either loosen the filters, or the nightly ingest
              hasn&apos;t stored those metrics for the universe yet.
            </p>
          )}
          {result.disclaimer ? (
            <p className="text-[11px] text-muted-foreground">{result.disclaimer}</p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
