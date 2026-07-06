"use client";

/**
 * Balance-sheet insights (D3).
 *
 * Upload a balance sheet (CSV/PDF) or type the line items in, and get
 * deterministic ratios + an Altman Z-score plus a grounded LLM narrative. The
 * math is computed server-side in a pure, unit-tested engine — the LLM only
 * explains the numbers, it never produces them.
 *
 * Advisory / educational only: there are no buy/sell affordances.
 */

import * as React from "react";
import { FileUp, Loader2, Sparkles, Upload } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Markdown } from "@/components/shared/markdown";
import {
  BS_FIELDS,
  useAnalyzeBalanceSheet,
  useUploadBalanceSheet,
  type AnalyzeResponse,
  type BalanceSheetInput,
  type BsField,
  type Ratio,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const FIELD_LABELS: Record<BsField, string> = {
  total_current_assets: "Total current assets",
  total_current_liabilities: "Total current liabilities",
  inventory: "Inventory",
  total_assets: "Total assets",
  total_liabilities: "Total liabilities",
  total_equity: "Total equity (net worth)",
  total_debt: "Total debt / borrowings",
  retained_earnings: "Retained earnings / reserves",
  ebit: "EBIT (operating profit)",
  interest_expense: "Interest expense",
  revenue: "Revenue (net sales)",
  market_cap: "Market cap (optional)",
};

const HEALTH_TONE: Record<Ratio["health"], string> = {
  strong: "text-emerald-700 dark:text-emerald-400 border-emerald-600/30 bg-emerald-500/5",
  adequate: "text-amber-700 dark:text-amber-400 border-amber-600/30 bg-amber-500/5",
  weak: "text-red-700 dark:text-red-400 border-red-600/30 bg-red-500/5",
  unknown: "text-muted-foreground border-border/60 bg-secondary/30",
};

const ZONE_TONE: Record<string, string> = {
  safe: "text-emerald-700 dark:text-emerald-400 border-emerald-600/40 bg-emerald-500/10",
  grey: "text-amber-700 dark:text-amber-400 border-amber-600/40 bg-amber-500/10",
  distress: "text-red-700 dark:text-red-400 border-red-600/40 bg-red-500/10",
  unknown: "text-muted-foreground border-border/60 bg-secondary/30",
};

type Mode = "upload" | "manual";

export default function BalanceSheetPage() {
  const [mode, setMode] = React.useState<Mode>("upload");
  const analyze = useAnalyzeBalanceSheet();
  const upload = useUploadBalanceSheet();

  const result: AnalyzeResponse | undefined = upload.data ?? analyze.data;
  const parsedFields = upload.data?.parsed_fields;
  const isPending = analyze.isPending || upload.isPending;
  const error = (analyze.error ?? upload.error) as Error | null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Balance-sheet insights"
        description="Upload a balance sheet (CSV or PDF) or enter the numbers — get liquidity, leverage, profitability and an Altman Z solvency score, explained. Educational, not advice."
      />

      {/* Mode toggle */}
      <div
        className="inline-flex items-center gap-1 border border-border bg-secondary/40 p-1"
        role="tablist"
        aria-label="Input mode"
      >
        {(["upload", "manual"] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className={cn(
              "px-4 py-1.5 font-label text-xs uppercase tracking-wider transition-colors",
              mode === m
                ? "bg-card text-primary shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {m === "upload" ? "Upload file" : "Enter manually"}
          </button>
        ))}
      </div>

      {mode === "upload" ? (
        <UploadCard
          onFile={(file) => upload.mutate({ file })}
          pending={upload.isPending}
        />
      ) : (
        <ManualForm
          onSubmit={(input) => analyze.mutate(input)}
          pending={analyze.isPending}
        />
      )}

      {error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error.message}
        </div>
      ) : null}

      {isPending ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Crunching the numbers…
        </div>
      ) : null}

      {result ? (
        <Results result={result} parsedFields={parsedFields} />
      ) : null}
    </div>
  );
}

function UploadCard({
  onFile,
  pending,
}: {
  onFile: (file: File) => void;
  pending: boolean;
}) {
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = React.useState(false);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) onFile(file);
      }}
      className={cn(
        "flex flex-col items-center justify-center gap-3 border border-dashed px-6 py-12 text-center transition-colors",
        dragging ? "border-primary bg-primary/5" : "border-border/70 bg-card",
      )}
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-border bg-secondary/50 text-muted-foreground">
        <FileUp className="h-5 w-5" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">Drop a CSV or PDF here</p>
        <p className="text-xs text-muted-foreground">
          Two-column CSV (label, value) works best. PDF text is extracted
          best-effort — review the parsed fields below.
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.pdf,text/csv,application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-1.5"
        disabled={pending}
        onClick={() => inputRef.current?.click()}
      >
        <Upload className="h-3.5 w-3.5" />
        Choose file
      </Button>
    </div>
  );
}

function ManualForm({
  onSubmit,
  pending,
}: {
  onSubmit: (input: BalanceSheetInput) => void;
  pending: boolean;
}) {
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [company, setCompany] = React.useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const input: BalanceSheetInput = { company: company.trim() || null };
    for (const f of BS_FIELDS) {
      const raw = values[f]?.trim();
      if (raw) {
        const n = Number(raw.replace(/,/g, ""));
        if (!Number.isNaN(n)) (input as Record<string, unknown>)[f] = n;
      }
    }
    onSubmit(input);
  };

  return (
    <form onSubmit={submit} className="space-y-4 border border-border/60 bg-card p-5">
      <div>
        <label className="eyebrow mb-1 block">Company (optional)</label>
        <Input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder="e.g. Reliance Industries"
          className="max-w-sm"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {BS_FIELDS.map((f) => (
          <div key={f}>
            <label className="eyebrow mb-1 block">{FIELD_LABELS[f]}</label>
            <Input
              inputMode="decimal"
              value={values[f] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [f]: e.target.value }))
              }
              placeholder="—"
            />
          </div>
        ))}
      </div>
      <Button type="submit" disabled={pending} className="gap-1.5">
        <Sparkles className="h-3.5 w-3.5" />
        Analyze
      </Button>
    </form>
  );
}

function Results({
  result,
  parsedFields,
}: {
  result: AnalyzeResponse;
  parsedFields?: string[];
}) {
  const { metrics } = result;
  const z = metrics.altman_z;

  return (
    <div className="space-y-5">
      {parsedFields ? (
        <p className="text-xs text-muted-foreground">
          {parsedFields.length
            ? `Extracted ${parsedFields.length} field${parsedFields.length === 1 ? "" : "s"}: ${parsedFields
                .map((f) => FIELD_LABELS[f as BsField] ?? f)
                .join(", ")}. Switch to “Enter manually” to correct anything.`
            : "Couldn’t extract structured line items — try a two-column CSV or enter values manually."}
        </p>
      ) : null}

      {/* Ratio cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {metrics.ratios.map((r) => (
          <div key={r.key} className={cn("border p-4", HEALTH_TONE[r.health])}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="eyebrow">{r.label}</span>
              <span className="font-label text-[10px] uppercase tracking-wider">
                {r.health}
              </span>
            </div>
            <div className="mt-1 font-mono text-2xl tabular-nums">
              {r.value === null
                ? "—"
                : r.key === "roce"
                  ? `${(r.value * 100).toFixed(1)}%`
                  : `${r.value.toFixed(2)}${r.key.includes("ratio") || r.key.includes("coverage") || r.key === "debt_to_equity" ? "×" : ""}`}
            </div>
            <p className="mt-1 text-xs leading-relaxed opacity-90">
              {r.interpretation}
            </p>
          </div>
        ))}
      </div>

      {/* Altman Z */}
      <div className={cn("border p-5", ZONE_TONE[z.zone])}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="eyebrow">Altman Z-score · solvency</span>
          <span className="font-label text-[10px] uppercase tracking-wider">
            {z.zone} zone{z.used_market_value ? " · uses market cap" : ""}
          </span>
        </div>
        <div className="mt-1 font-mono text-3xl tabular-nums">
          {z.score === null ? "—" : z.score.toFixed(2)}
        </div>
        <p className="mt-1 text-sm leading-relaxed opacity-90">{z.interpretation}</p>
      </div>

      {/* LLM narrative */}
      <section className="border border-border/60 bg-card p-5">
        <div className="mb-2 flex items-center gap-1.5">
          <span className="eyebrow">Insights</span>
          {!result.used_llm ? (
            <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
              · deterministic summary (LLM offline)
            </span>
          ) : null}
        </div>
        <Markdown>{result.insight_markdown}</Markdown>
        {result.disclaimer ? (
          <p className="mt-3 border-t border-border/40 pt-3 text-[11px] text-muted-foreground">
            {result.disclaimer}
          </p>
        ) : null}
      </section>
    </div>
  );
}
