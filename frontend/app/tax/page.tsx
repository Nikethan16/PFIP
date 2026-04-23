"use client";

import * as React from "react";
import { useDropzone } from "react-dropzone";
import { Download, FileUp, Upload } from "lucide-react";

import { Card, Metric, Text } from "@tremor/react";
import {
  Card as ShadCard,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { StaleBadge } from "@/components/shared/stale-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { ScheduleFaTable } from "@/components/tax/schedule-fa-table";
import { SurchargeGauge } from "@/components/tax/surcharge-gauge";
import { RegimeComparison } from "@/components/tax/regime-comparison";
import {
  downloadTaxExport,
  useAuthToken,
  useImportTaxCsv,
  useScheduleFA,
  useTaxDetails,
  useTaxSummary,
  type SupportedBroker,
} from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { toast } from "@/components/ui/toast";

const BROKERS: Array<{
  id: SupportedBroker;
  label: string;
  hint: string;
  group: "india-equity" | "us-equity" | "crypto";
}> = [
  { id: "zerodha", label: "Zerodha", hint: "Console tradebook · equity + F&O", group: "india-equity" },
  { id: "icicidirect", label: "ICICIdirect", hint: "Equity contract note CSV", group: "india-equity" },
  { id: "groww", label: "Groww", hint: "Stocks + MF combined", group: "india-equity" },
  { id: "indmoney", label: "INDmoney", hint: "US stocks (USD)", group: "us-equity" },
  { id: "vested", label: "Vested", hint: "US stocks (USD)", group: "us-equity" },
  { id: "wazirx", label: "WazirX", hint: "Crypto · deprecated but kept", group: "crypto" },
  { id: "coindcx", label: "CoinDCX", hint: "Crypto trades", group: "crypto" },
  { id: "binance", label: "Binance", hint: "Crypto exchange + P2P", group: "crypto" },
  { id: "coinbase", label: "Coinbase", hint: "Crypto · US exchange", group: "crypto" },
  { id: "kraken", label: "Kraken", hint: "Crypto · ledgers export", group: "crypto" },
];

export default function TaxPage() {
  const { data: summary, isLoading, error } = useTaxSummary();
  const { data: scheduleFa, isLoading: loadingFa } = useScheduleFA();
  const { data: details } = useTaxDetails();
  const token = useAuthToken();
  const [exporting, setExporting] = React.useState(false);

  const fy = summary?.fy ?? details?.fy ?? "2026-27";

  const onExport = async () => {
    setExporting(true);
    try {
      const blob = await downloadTaxExport(fy, token);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pfip-tax-${fy}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Export ready — saved to Downloads");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tax</h1>
          <p className="text-sm text-muted-foreground">
            India-first: STCG / LTCG, crypto flat 30%, Schedule FA for foreign
            assets, DTAA credit via Form 67.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {summary ? <StaleBadge updatedAt={summary.updated_at} /> : null}
          <Button
            onClick={onExport}
            disabled={exporting}
            variant="outline"
            size="sm"
            className="gap-1"
          >
            <Download className="h-3 w-3" />
            {exporting ? "Exporting…" : "Export for CA"}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {isLoading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load tax summary: {(error as Error).message}
        </div>
      ) : !summary ? (
        <EmptyState
          title="No tax data yet"
          description="Import broker CSVs below to compute STCG / LTCG / VDA numbers."
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Card>
            <Text>STCG (equity)</Text>
            <Metric>{formatINR(summary.stcg_equity_inr)}</Metric>
            <Text>FY {summary.fy}</Text>
          </Card>
          <Card>
            <Text>LTCG (equity)</Text>
            <Metric>{formatINR(summary.ltcg_equity_inr)}</Metric>
          </Card>
          <Card>
            <Text>VDA flat 30%</Text>
            <Metric>{formatINR(summary.crypto_flat_tax_inr)}</Metric>
            <Text>
              Gains{" "}
              {formatINR(
                summary.stcg_crypto_inr + summary.ltcg_crypto_inr,
              )}
            </Text>
          </Card>
          <Card>
            <Text>Slab income</Text>
            <Metric>{formatINR(details?.slab_income_inr ?? 0)}</Metric>
            <Text>
              Marginal rate {details?.marginal_rate_pct ?? 30}%
            </Text>
          </Card>
          <Card>
            <Text>Dividends</Text>
            <Metric>{formatINR(summary.dividend_income_inr)}</Metric>
            <Text>Interest {formatINR(summary.interest_income_inr)}</Text>
          </Card>
          <Card>
            <Text>DTAA credit</Text>
            <Metric>{formatINR(summary.dtaa_credit_available_inr)}</Metric>
            <Text>Foreign {formatINR(summary.foreign_income_inr)}</Text>
          </Card>
        </div>
      )}

      {/* Regime comparison + surcharge + 80C */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ShadCard>
          <CardHeader>
            <CardTitle className="text-base">Old vs new regime</CardTitle>
            <CardDescription>Which one gives you a lower bill?</CardDescription>
          </CardHeader>
          <CardContent>
            {details ? (
              <RegimeComparison
                oldRegimeInr={details.old_regime_tax_inr}
                newRegimeInr={details.new_regime_tax_inr}
              />
            ) : (
              <Skeleton className="h-40 w-full" />
            )}
          </CardContent>
        </ShadCard>

        <ShadCard>
          <CardHeader>
            <CardTitle className="text-base">Surcharge cliff</CardTitle>
            <CardDescription>
              India slabs: 50L / 1Cr / 2Cr / 5Cr.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {details ? (
              <SurchargeGauge
                incomeInr={details.total_income_inr}
                thresholds={details.surcharge_thresholds}
              />
            ) : (
              <Skeleton className="h-32 w-full" />
            )}
          </CardContent>
        </ShadCard>

        <ShadCard>
          <CardHeader>
            <CardTitle className="text-base">80C optimizer</CardTitle>
            <CardDescription>
              Fill cap remaining × marginal rate.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {details ? (
              <EightyCOptimizer
                used={details.eighty_c_used_inr}
                cap={details.eighty_c_cap_inr}
                marginal={details.marginal_rate_pct}
              />
            ) : (
              <Skeleton className="h-32 w-full" />
            )}
          </CardContent>
        </ShadCard>
      </div>

      {/* Schedule FA */}
      <ShadCard>
        <CardHeader>
          <CardTitle>Schedule FA</CardTitle>
          <CardDescription>
            Foreign assets disclosure — generated from US / foreign / crypto
            holdings.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loadingFa ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <ScheduleFaTable rows={scheduleFa ?? []} />
          )}
        </CardContent>
      </ShadCard>

      {/* Form 67 preview */}
      <ShadCard>
        <CardHeader>
          <CardTitle>Form 67 preview</CardTitle>
          <CardDescription>
            DTAA credit claim preview — confirm each line with your CA before
            filing.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {details?.form_67_lines.length ? (
            <ol className="space-y-1 text-xs text-muted-foreground">
              {details.form_67_lines.map((line, i) => (
                <li
                  key={i}
                  className="rounded border bg-muted/30 px-2 py-1 font-mono"
                >
                  {i + 1}. {line}
                </li>
              ))}
            </ol>
          ) : (
            <div className="text-xs text-muted-foreground">
              No Form 67 lines generated yet (no foreign income detected).
            </div>
          )}
        </CardContent>
      </ShadCard>

      {/* CSV imports */}
      <div>
        <h2 className="mb-1 text-lg font-semibold">Import CSVs</h2>
        <p className="mb-3 text-xs text-muted-foreground">
          Drag-and-drop from the brokers below. Duplicates are de-duped on the
          backend via transaction hash.
        </p>
        {(["india-equity", "us-equity", "crypto"] as const).map((group) => (
          <div key={group} className="mb-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {group.replace("-", " ")}
            </h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {BROKERS.filter((b) => b.group === group).map((b) => (
                <BrokerDropzone
                  key={b.id}
                  broker={b.id}
                  label={b.label}
                  hint={b.hint}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EightyCOptimizer({
  used,
  cap,
  marginal,
}: {
  used: number;
  cap: number;
  marginal: number;
}) {
  const remaining = Math.max(0, cap - used);
  const savings = remaining * (marginal / 100);
  const pct = Math.min(100, (used / cap) * 100);

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-xs text-muted-foreground">Used</div>
        <div className="text-sm font-semibold tabular-nums">
          {formatINR(used)} / {formatINR(cap)}
        </div>
      </div>
      <div className="h-2 w-full overflow-hidden rounded bg-muted">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
          aria-label="80C usage"
        />
      </div>
      <div className="rounded-md border bg-muted/30 p-2 text-xs">
        {remaining > 0 ? (
          <>
            Add{" "}
            <span className="font-semibold">{formatINR(remaining)}</span> to
            max out 80C → saves{" "}
            <span className="font-semibold">{formatINR(savings)}</span> at your
            marginal {marginal}% rate.
          </>
        ) : (
          <>80C maxed out. No further deductions available under this section.</>
        )}
      </div>
    </div>
  );
}

function BrokerDropzone({
  broker,
  label,
  hint,
}: {
  broker: SupportedBroker;
  label: string;
  hint: string;
}) {
  const importer = useImportTaxCsv();
  const [progress, setProgress] = React.useState<number | null>(null);

  const onDrop = React.useCallback(
    (files: File[]) => {
      const file = files[0];
      if (!file) return;
      setProgress(0);
      // Fake progress since fetch doesn't expose upload progress without XHR.
      const tick = window.setInterval(() => {
        setProgress((p) => (p == null ? 10 : Math.min(95, p + 15)));
      }, 250);
      importer.mutate(
        { broker, file },
        {
          onSuccess: (res) => {
            setProgress(100);
            window.clearInterval(tick);
            const msg = `${broker}: imported ${res.imported}, rejected ${res.rejected}`;
            if (res.errors.length) {
              toast.warning(msg + ` · ${res.errors.length} errors`);
            } else {
              toast.success(msg);
            }
            window.setTimeout(() => setProgress(null), 1200);
          },
          onError: (err) => {
            window.clearInterval(tick);
            setProgress(null);
            toast.error((err as Error).message);
          },
        },
      );
    },
    [broker, importer],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.ms-excel": [".csv"],
    },
    maxFiles: 1,
  });

  return (
    <div>
      <div
        {...getRootProps()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-4 text-sm transition-colors ${
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-muted hover:border-primary/50"
        }`}
        role="button"
        tabIndex={0}
        aria-label={`Upload CSV for ${label}`}
      >
        <input {...getInputProps()} />
        <div className="flex items-center gap-3">
          {importer.isPending ? (
            <Upload className="h-5 w-5 animate-pulse text-primary" />
          ) : (
            <FileUp className="h-5 w-5 text-muted-foreground" />
          )}
          <div className="min-w-0">
            <div className="truncate font-medium">{label}</div>
            <div className="truncate text-xs text-muted-foreground">
              {importer.isPending
                ? "Uploading…"
                : isDragActive
                  ? "Drop the CSV here"
                  : hint}
            </div>
          </div>
        </div>
      </div>
      {progress != null ? (
        <div className="mt-1 h-1 w-full overflow-hidden rounded bg-muted">
          <div
            className="h-full bg-primary transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
