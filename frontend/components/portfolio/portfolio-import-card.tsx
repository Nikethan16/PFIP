"use client";

import * as React from "react";
import { useDropzone } from "react-dropzone";
import {
  CheckCircle2,
  FileUp,
  Loader2,
  RotateCcw,
  Upload,
  X,
} from "lucide-react";

import {
  usePortfolioImport,
  type PortfolioImportResult,
  type SupportedBroker,
} from "@/lib/api";
import { toast } from "@/components/ui/toast";
import { formatINR } from "@/lib/utils";

/**
 * Portfolio CSV → holdings importer.
 *
 * Two-step, dry-run-first flow against `POST /portfolio/import`:
 *   1. Drop a tradebook → upload with `dry_run=true` → render a parse preview
 *      (rows + rejects/errors). Nothing is written.
 *   2. Confirm → re-post the SAME file with `dry_run=false` → the backend
 *      persists the ledger rows and rebuilds holdings in one call, returning
 *      `holdings_rebuilt`. We surface that and the holdings query is invalidated.
 *
 * Broker is optional — the CSV router auto-detects the schema when omitted, so
 * the only required input is the file. Mirrors the Tax page's BrokerDropzone
 * styling but adds the confirm gate (this path mutates the portfolio).
 */

// Broker hint options. "" = let the backend auto-detect the schema.
const BROKER_OPTIONS: Array<{ value: "" | SupportedBroker; label: string }> = [
  { value: "", label: "Auto-detect" },
  { value: "zerodha", label: "Zerodha" },
  { value: "icicidirect", label: "ICICIdirect" },
  { value: "groww", label: "Groww" },
  { value: "indmoney", label: "INDmoney" },
  { value: "vested", label: "Vested" },
  { value: "wazirx", label: "WazirX" },
  { value: "coindcx", label: "CoinDCX" },
  { value: "binance", label: "Binance" },
  { value: "coinbase", label: "Coinbase" },
  { value: "kraken", label: "Kraken" },
];

export function PortfolioImportCard() {
  const importer = usePortfolioImport();

  // The file awaiting confirmation + the dry-run preview it produced.
  const [file, setFile] = React.useState<File | null>(null);
  const [broker, setBroker] = React.useState<"" | SupportedBroker>("");
  const [preview, setPreview] = React.useState<PortfolioImportResult | null>(
    null,
  );
  // The persisted result after a confirmed import (dry_run=false).
  const [committed, setCommitted] = React.useState<PortfolioImportResult | null>(
    null,
  );

  const reset = React.useCallback(() => {
    setFile(null);
    setPreview(null);
    setCommitted(null);
    importer.reset();
  }, [importer]);

  const onDrop = React.useCallback(
    (files: File[]) => {
      const f = files[0];
      if (!f) return;
      setFile(f);
      setCommitted(null);
      setPreview(null);
      importer.mutate(
        { file: f, broker: broker || null, dry_run: true },
        {
          onSuccess: (res) => {
            setPreview(res);
            if (!res.imported && !res.rejected) {
              toast.warning("No rows parsed from that file.");
            }
          },
          onError: (err) => {
            setFile(null);
            toast.error((err as Error).message);
          },
        },
      );
    },
    [broker, importer],
  );

  const onConfirm = React.useCallback(() => {
    if (!file) return;
    importer.mutate(
      { file, broker: broker || null, dry_run: false },
      {
        onSuccess: (res) => {
          setCommitted(res);
          setPreview(null);
          setFile(null);
          toast.success(
            `Imported ${res.persisted} rows · ${res.holdings_rebuilt} holdings rebuilt`,
          );
        },
        onError: (err) => toast.error((err as Error).message),
      },
    );
  }, [file, broker, importer]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.ms-excel": [".csv"],
    },
    maxFiles: 1,
    disabled: importer.isPending || preview != null,
  });

  const busy = importer.isPending;

  return (
    <section className="border border-border/60 bg-card">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/40 p-5">
        <div>
          <div className="eyebrow">Data in</div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Import holdings from CSV
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Drop a broker tradebook to rebuild your holdings. We preview the
            parsed rows first — nothing is written until you confirm. Re-importing
            is safe (duplicates are de-duped server-side).
          </p>
        </div>
        <label className="flex flex-col gap-1">
          <span className="eyebrow">Broker</span>
          <select
            value={broker}
            onChange={(e) => setBroker(e.target.value as "" | SupportedBroker)}
            disabled={busy || preview != null}
            aria-label="Broker"
            className="border border-border bg-background px-3 py-2 font-mono text-xs tracking-tight focus:border-primary focus:outline-none disabled:opacity-60"
          >
            {BROKER_OPTIONS.map((o) => (
              <option key={o.value || "auto"} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="space-y-4 p-5">
        {/* Committed success banner. */}
        {committed ? (
          <div className="flex items-start justify-between gap-3 border border-emerald-600/30 bg-emerald-600/5 p-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700 dark:text-emerald-400" />
              <div>
                <div className="font-label text-xs uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Import complete
                </div>
                <p className="mt-1 text-sm">
                  Persisted{" "}
                  <span className="font-mono font-semibold tabular-nums">
                    {committed.persisted}
                  </span>{" "}
                  ledger rows ·{" "}
                  <span className="font-mono font-semibold tabular-nums">
                    {committed.holdings_rebuilt}
                  </span>{" "}
                  holding{committed.holdings_rebuilt === 1 ? "" : "s"} rebuilt.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 font-label text-[11px] uppercase tracking-wider text-foreground transition-colors hover:bg-accent"
            >
              <RotateCcw className="h-3 w-3" />
              Import another
            </button>
          </div>
        ) : null}

        {/* Dropzone — hidden once a preview is pending confirmation. */}
        {!preview && !committed ? (
          <div
            {...getRootProps()}
            className={`cursor-pointer border border-dashed p-6 text-sm transition-colors ${
              isDragActive
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/50 hover:bg-accent/30"
            } ${busy ? "pointer-events-none opacity-70" : ""}`}
            role="button"
            tabIndex={0}
            aria-label="Upload portfolio CSV"
          >
            <input {...getInputProps()} />
            <div className="flex items-center gap-3">
              {busy ? (
                <Upload className="h-5 w-5 animate-pulse text-primary" />
              ) : (
                <FileUp className="h-5 w-5 text-muted-foreground" />
              )}
              <div className="min-w-0">
                <div className="font-medium">
                  {busy
                    ? "Parsing…"
                    : isDragActive
                      ? "Drop the CSV here"
                      : "Drag a tradebook CSV here, or click to browse"}
                </div>
                <div className="text-xs text-muted-foreground">
                  Zerodha · ICICIdirect · Groww · INDmoney · Vested · WazirX ·
                  CoinDCX · Binance · Coinbase · Kraken
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {/* Preview — parsed rows + rejects, with confirm/cancel. */}
        {preview ? (
          <ImportPreview
            preview={preview}
            fileName={file?.name ?? "CSV"}
            confirming={busy}
            onConfirm={onConfirm}
            onCancel={reset}
          />
        ) : null}
      </div>
    </section>
  );
}

function ImportPreview({
  preview,
  fileName,
  confirming,
  onConfirm,
  onCancel,
}: {
  preview: PortfolioImportResult;
  fileName: string;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const rows = preview.rows ?? [];
  const shown = rows.slice(0, 50);
  const canConfirm = preview.imported > 0;

  return (
    <div className="space-y-4">
      {/* Summary chips. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">
          {fileName}
        </span>
        {preview.broker ? (
          <span className="border border-border/60 bg-secondary/40 px-2 py-0.5 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
            {preview.broker}
          </span>
        ) : null}
        <span className="border border-emerald-600/30 bg-emerald-600/5 px-2 py-0.5 font-label text-[10px] uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
          {preview.imported} parsed
        </span>
        {preview.rejected > 0 ? (
          <span className="border border-amber-500/30 bg-amber-500/5 px-2 py-0.5 font-label text-[10px] uppercase tracking-wider text-amber-700 dark:text-amber-400">
            {preview.rejected} rejected
          </span>
        ) : null}
      </div>

      {/* Parsed rows table. */}
      {shown.length ? (
        <div className="max-h-72 overflow-auto border border-border/50">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-secondary/60 backdrop-blur">
              <tr className="font-label uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2 text-left font-normal">Symbol</th>
                <th className="px-3 py-2 text-left font-normal">Kind</th>
                <th className="px-3 py-2 text-right font-normal">Qty</th>
                <th className="px-3 py-2 text-right font-normal">Amount (INR)</th>
                <th className="px-3 py-2 text-left font-normal">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {shown.map((r, i) => (
                <tr key={i} className="hover:bg-accent/30">
                  <td className="px-3 py-1.5 font-mono">{r.symbol ?? "—"}</td>
                  <td className="px-3 py-1.5 font-label uppercase tracking-wider text-muted-foreground">
                    {r.kind ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                    {r.qty != null ? r.qty : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                    {r.amount_inr != null ? formatINR(r.amount_inr) : "—"}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-muted-foreground">
                    {r.time ? r.time.slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > shown.length ? (
            <div className="border-t border-border/40 bg-secondary/30 px-3 py-1.5 text-[11px] text-muted-foreground">
              Showing first {shown.length} of {rows.length} parsed rows.
            </div>
          ) : null}
        </div>
      ) : (
        <div className="border border-dashed p-4 text-center text-xs text-muted-foreground">
          No rows parsed from this file. Check the broker selection or the
          export format.
        </div>
      )}

      {/* Rejects / errors. */}
      {preview.errors.length ? (
        <div className="border border-amber-500/30 bg-amber-500/5 p-3">
          <div className="eyebrow mb-1.5 text-amber-700 dark:text-amber-400">
            {preview.errors.length} row
            {preview.errors.length === 1 ? "" : "s"} rejected
          </div>
          <ul className="max-h-32 space-y-1 overflow-auto text-[11px] text-muted-foreground">
            {preview.errors.slice(0, 20).map((e, i) => (
              <li key={i} className="font-mono">
                • {e}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Confirm / cancel. */}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={confirming}
          className="inline-flex items-center gap-1.5 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent disabled:opacity-60"
        >
          <X className="h-3.5 w-3.5" />
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={confirming || !canConfirm}
          className="inline-flex items-center gap-2 bg-primary px-4 py-2 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110 disabled:opacity-60"
        >
          {confirming ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Rebuilding…
            </>
          ) : (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" />
              Confirm · rebuild {preview.imported} row
              {preview.imported === 1 ? "" : "s"}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
