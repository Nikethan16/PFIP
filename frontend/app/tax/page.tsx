"use client";

/**
 * Sahara "Tax Ledger" — the Tax page.
 *
 * India-first capital-gains + VDA worktop restyled to the institutional-terminal
 * aesthetic. Every figure traces to a real hook (no fabrication):
 *
 *   - KPI strip            ← useTaxSummary(fy)   (/tax/summary, fy REQUIRED)
 *   - slab / marginal      ← useTaxDetails(fy)   (/tax/details)
 *   - regime comparison    ← useTaxDetails(fy).old_/new_regime_tax_inr
 *   - surcharge cliff      ← useTaxDetails(fy).total_income_inr + thresholds
 *   - 80C optimizer        ← useTaxDetails(fy).eighty_c_*
 *   - Schedule FA          ← useScheduleFA(fy)   (/tax/schedule-fa rows)
 *   - Form 67 preview      ← useTaxDetails(fy).form_67_lines
 *   - tax-loss harvest     ← useHarvestPlan()    (/tax/harvest, on demand)
 *   - CSV import           ← useImportTaxCsv()   (/tax/import/{broker})
 *   - PDF export           ← downloadTaxExport() (/tax/export)
 *
 * ADVISORY ONLY — the disclaimer stays visible; nothing here files anything.
 * The FY selector drives all four queries through their `fy` param, so changing
 * the year refetches honestly rather than reslicing stale data.
 */

import * as React from "react";
import { useDropzone } from "react-dropzone";
import {
  AlertTriangle,
  Download,
  FileUp,
  Scissors,
  Upload,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { Kpi } from "@/components/shared/kpi";
import { FreshnessBadge } from "@/components/shared/freshness-badge";
import { ScheduleFaTable } from "@/components/tax/schedule-fa-table";
import { SurchargeGauge } from "@/components/tax/surcharge-gauge";
import { RegimeComparison } from "@/components/tax/regime-comparison";
import {
  currentFy,
  downloadTaxExport,
  useAuthToken,
  useHarvestPlan,
  useImportTaxCsv,
  useScheduleFA,
  useTaxDetails,
  useTaxSummary,
  type HarvestPlan,
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

const GROUP_LABELS: Record<"india-equity" | "us-equity" | "crypto", string> = {
  "india-equity": "India equity",
  "us-equity": "US equity",
  crypto: "Crypto",
};

/** Trailing window of selectable Indian fiscal years (current + 4 prior). */
function fyOptions(): string[] {
  const now = new Date();
  const current = currentFy(now);
  const startYear = Number(current.slice(0, 4));
  return Array.from({ length: 5 }, (_, i) => {
    const sy = startYear - i;
    const endYY = String((sy + 1) % 100).padStart(2, "0");
    return `${sy}-${endYY}`;
  });
}

export default function TaxPage() {
  // The FY selector drives all four /tax/* queries through their `fy` param.
  const [fy, setFy] = React.useState<string>(() => currentFy());

  const { data: summary, isLoading, error } = useTaxSummary(fy);
  const { data: scheduleFa, isLoading: loadingFa } = useScheduleFA(fy);
  const { data: details } = useTaxDetails(fy);
  const token = useAuthToken();
  const [exporting, setExporting] = React.useState(false);

  const options = React.useMemo(() => fyOptions(), []);

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
    <div className="space-y-8">
      {/* Header — serif "Tax" + advisory eyebrow + FY selector + export. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Capital gains · VDA · Schedule FA // advisory only
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Tax Ledger
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            India-first STCG / LTCG, crypto flat 30%, foreign-asset disclosure
            and DTAA credit via Form&nbsp;67 — computed from your imported
            broker trades.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="eyebrow">Fiscal year</span>
            <select
              value={fy}
              onChange={(e) => setFy(e.target.value)}
              aria-label="Fiscal year"
              className="border border-border bg-background px-3 py-2 font-mono text-sm tracking-tight tabular-nums focus:border-primary focus:outline-none"
            >
              {options.map((o) => (
                <option key={o} value={o}>
                  FY {o}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="inline-flex items-center gap-2 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent disabled:opacity-60"
          >
            <Download className="h-3.5 w-3.5" />
            {exporting ? "Exporting…" : "Export for CA"}
          </button>
        </div>
      </div>

      {/* Disclaimer — advisory-only, must stay visible. */}
      <div className="flex items-start gap-2 border border-primary/30 bg-primary/5 px-4 py-3 text-xs text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
        <p>
          {summary?.disclaimer ??
            "Estimates only — not tax advice. Confirm every figure with a qualified CA before filing. PFIP never files or transmits returns."}
        </p>
      </div>

      {/* KPI strip — headline tax figures (real TaxSummary fields). */}
      {isLoading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load tax summary: {(error as Error).message}
        </div>
      ) : !summary ? (
        <section className="border border-border/60 bg-card p-6">
          <EmptyState
            title="No tax data yet"
            description="Import broker CSVs below to compute STCG / LTCG / VDA numbers for the selected fiscal year."
          />
        </section>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Kpi
            label="STCG · equity"
            value={formatINR(summary.equity_stcg_gain_inr)}
            hint="short-term gain"
          />
          <Kpi
            label="LTCG · equity"
            value={formatINR(summary.equity_ltcg_gain_inr)}
            hint="long-term gain"
          />
          <Kpi
            label="VDA flat 30%"
            // Backend exposes VDA *gains*; the flat-30% liability is derived.
            value={formatINR(summary.vda_gain_inr * 0.3)}
            hint={`gains ${formatINR(summary.vda_gain_inr)}`}
          />
          <Kpi
            label="Slab income"
            value={formatINR(details?.slab_income_inr ?? 0)}
            hint={`marginal ${details?.marginal_rate_pct ?? 30}%`}
          />
          <Kpi
            label="Dividends"
            value={formatINR(summary.dividend_inr)}
            hint={`TDS credit ${formatINR(summary.vda_tds_credit_inr)}`}
          />
          <Kpi
            label="Total tax"
            accent
            value={formatINR(summary.total_tax_inr)}
            valueClassName="text-primary"
            hint={`${summary.event_count} taxable events`}
          />
        </div>
      )}

      {/* Surcharge cliff warnings (free-text from the summary). */}
      {summary?.surcharge_cliff_warnings.length ? (
        <div className="border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <div className="eyebrow mb-1.5 flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            Surcharge cliff watch
          </div>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {summary.surcharge_cliff_warnings.map((w, i) => (
              <li key={i}>• {w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Regime comparison + surcharge + 80C — editorial sectioned cards. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <EditorialSection
          eyebrow="Regime planner"
          title="Old vs new regime"
          subtitle="Which one gives you a lower bill?"
        >
          {details ? (
            <RegimeComparison
              oldRegimeInr={details.old_regime_tax_inr}
              newRegimeInr={details.new_regime_tax_inr}
            />
          ) : (
            <Skeleton className="h-40 w-full" />
          )}
        </EditorialSection>

        <EditorialSection
          eyebrow="Surcharge cliff"
          title="Where your income sits"
          subtitle="India slabs · 50L / 1Cr / 2Cr / 5Cr"
        >
          {details ? (
            <SurchargeGauge
              incomeInr={details.total_income_inr}
              thresholds={details.surcharge_thresholds}
            />
          ) : (
            <Skeleton className="h-32 w-full" />
          )}
        </EditorialSection>

        <EditorialSection
          eyebrow="80C optimizer"
          title="Deduction headroom"
          subtitle="Fill cap remaining × marginal rate"
        >
          {details ? (
            <EightyCOptimizer
              used={details.eighty_c_used_inr}
              cap={details.eighty_c_cap_inr}
              marginal={details.marginal_rate_pct}
            />
          ) : (
            <Skeleton className="h-32 w-full" />
          )}
        </EditorialSection>
      </div>

      {/* Schedule FA — editorial table, honest about the peak/cost basis. */}
      <section className="border border-border/60 bg-card">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/40 p-5">
          <div>
            <div className="eyebrow flex items-center gap-2">
              Foreign assets
              <FreshnessBadge sources={["fx_rates_daily"]} />
            </div>
            <h3 className="mt-1 font-serif text-xl tracking-tight">
              Schedule FA
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Generated from US / foreign / crypto holdings. Peak balances use a
              high-water mark where lot history exists, else a cost-basis
              approximation — verify against statements before you file.
            </p>
          </div>
        </div>
        <div className="p-5">
          {loadingFa ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <ScheduleFaTable rows={scheduleFa ?? []} />
          )}
        </div>
      </section>

      {/* Form 67 preview — editorial section. */}
      <section className="border border-border/60 bg-card">
        <div className="border-b border-border/40 p-5">
          <div className="eyebrow">DTAA credit</div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Form 67 preview
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Foreign tax-credit claim lines — confirm each with your CA before
            filing.
          </p>
        </div>
        <div className="p-5">
          {details?.form_67_lines.length ? (
            <ol className="space-y-1.5">
              {details.form_67_lines.map((line, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 border border-border/50 bg-secondary/30 px-3 py-2 font-mono text-xs"
                >
                  <span className="shrink-0 text-muted-foreground tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="text-foreground">{line}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-muted-foreground">
              No Form&nbsp;67 lines generated yet — no foreign income detected
              for FY&nbsp;{fy}.
            </p>
          )}
        </div>
      </section>

      {/* Tax-loss harvesting — on-demand plan from /tax/harvest. */}
      <HarvestSection fy={fy} />

      {/* CSV imports — editorial section with restyled dropzones. */}
      <section className="border border-border/60 bg-card">
        <div className="border-b border-border/40 p-5">
          <div className="eyebrow">Data in</div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Import broker CSVs
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Drag-and-drop tradebooks below. Duplicates are de-duped server-side
            via transaction hash, so re-importing is safe.
          </p>
        </div>
        <div className="space-y-6 p-5">
          {(["india-equity", "us-equity", "crypto"] as const).map((group) => (
            <div key={group}>
              <h4 className="eyebrow mb-3">{GROUP_LABELS[group]}</h4>
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
      </section>
    </div>
  );
}

/** Editorial card chrome: eyebrow + serif title + subtitle, then children. */
function EditorialSection({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow">{eyebrow}</div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">{title}</h3>
        {subtitle ? (
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      <div className="flex-1 p-5">{children}</div>
    </section>
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
        <div className="eyebrow">Used</div>
        <div className="font-mono text-sm font-semibold tabular-nums">
          {formatINR(used)} / {formatINR(cap)}
        </div>
      </div>
      <div className="h-2 w-full overflow-hidden bg-muted">
        <div
          className="h-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-label="80C usage"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      <div className="border border-border/50 bg-secondary/30 p-3 text-xs text-muted-foreground">
        {remaining > 0 ? (
          <>
            Add{" "}
            <span className="font-mono font-semibold text-foreground tabular-nums">
              {formatINR(remaining)}
            </span>{" "}
            to max out 80C → saves{" "}
            <span className="font-mono font-semibold text-foreground tabular-nums">
              {formatINR(savings)}
            </span>{" "}
            at your marginal {marginal}% rate.
          </>
        ) : (
          <>80C maxed out. No further deductions available under this section.</>
        )}
      </div>
    </div>
  );
}

/**
 * Tax-loss harvesting plan. Computes on demand against /tax/harvest for the
 * selected FY (the endpoint scans open lots for realisable losses that offset
 * realised gains). Renders an honest empty/zero state — harvesting only
 * surfaces lots that are actually sitting at a loss.
 */
function HarvestSection({ fy }: { fy: string }) {
  const harvest = useHarvestPlan();
  const [plan, setPlan] = React.useState<HarvestPlan | null>(null);

  const onRun = () => {
    harvest.mutate(
      { fy },
      {
        onSuccess: (res) => setPlan(res),
        onError: (err) => toast.error((err as Error).message),
      },
    );
  };

  return (
    <section className="border border-border/60 bg-card">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/40 p-5">
        <div>
          <div className="eyebrow">Optimisation</div>
          <h3 className="mt-1 font-serif text-xl tracking-tight">
            Tax-loss harvesting
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Scan open lots for realisable losses that offset this year&apos;s
            gains. Suggestions only — you decide what to sell.
          </p>
        </div>
        <button
          type="button"
          onClick={onRun}
          disabled={harvest.isPending}
          className="inline-flex items-center gap-2 border border-border px-4 py-2 font-label text-xs uppercase tracking-wider text-foreground transition-colors hover:bg-accent disabled:opacity-60"
        >
          <Scissors className="h-3.5 w-3.5" />
          {harvest.isPending ? "Scanning…" : "Run scan"}
        </button>
      </div>
      <div className="p-5">
        {harvest.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : harvest.isError ? (
          <div className="border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
            Couldn&apos;t compute a harvest plan: {(harvest.error as Error).message}
          </div>
        ) : !plan ? (
          <p className="text-xs text-muted-foreground">
            Run the scan to see loss lots that could offset realised gains for
            FY&nbsp;{fy}. Nothing is sold — these are advisory suggestions you
            confirm with your CA.
          </p>
        ) : !plan.suggestions.length ? (
          <div className="border border-dashed p-4 text-center text-xs text-muted-foreground">
            No harvestable losses found across {plan.n_lots_evaluated} lot
            {plan.n_lots_evaluated === 1 ? "" : "s"}. Either you have no open
            positions at a loss, or none would offset a realised gain this year.
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div className="border border-border/50 bg-secondary/40 p-3">
                <div className="eyebrow">Harvestable loss</div>
                <div className="mt-0.5 font-mono text-base font-semibold tabular-nums">
                  {formatINR(Number(plan.total_loss_inr))}
                </div>
              </div>
              <div className="border border-border/50 bg-secondary/40 p-3">
                <div className="eyebrow">Est. tax saved</div>
                <div className="mt-0.5 font-mono text-base font-semibold tabular-nums text-primary">
                  {formatINR(Number(plan.total_tax_saved_inr))}
                </div>
              </div>
              <div className="border border-border/50 bg-secondary/40 p-3">
                <div className="eyebrow">Lots evaluated</div>
                <div className="mt-0.5 font-mono text-base font-semibold tabular-nums">
                  {plan.n_lots_evaluated}
                </div>
              </div>
            </div>

            <div className="divide-y divide-border/40 border border-border/50">
              <div className="hidden grid-cols-12 gap-2 bg-secondary/30 px-3 py-2 font-label text-[10px] uppercase tracking-wider text-muted-foreground sm:grid">
                <span className="col-span-3">Symbol</span>
                <span className="col-span-2">Term</span>
                <span className="col-span-2 text-right">Qty</span>
                <span className="col-span-2 text-right">Loss</span>
                <span className="col-span-3 text-right">Tax saved</span>
              </div>
              {plan.suggestions.map((s) => (
                <div
                  key={s.lot_id}
                  className="grid grid-cols-2 gap-2 px-3 py-2.5 text-sm sm:grid-cols-12"
                >
                  <div className="sm:col-span-3">
                    <div className="font-medium">{s.symbol}</div>
                    <div className="font-mono text-[10px] uppercase text-muted-foreground">
                      {s.asset_class} · offsets {s.offsets_against}
                    </div>
                  </div>
                  <div className="font-label text-xs uppercase tracking-wider text-muted-foreground sm:col-span-2">
                    {s.term}
                  </div>
                  <div className="font-mono text-xs tabular-nums sm:col-span-2 sm:text-right">
                    {s.qty}
                  </div>
                  <div className="font-mono text-xs tabular-nums text-red-700 dark:text-red-400 sm:col-span-2 sm:text-right">
                    {formatINR(Number(s.loss_inr))}
                  </div>
                  <div className="font-mono text-xs font-semibold tabular-nums text-primary sm:col-span-3 sm:text-right">
                    {formatINR(Number(s.estimated_tax_saved_inr))}
                    {s.warning ? (
                      <div className="mt-0.5 font-label text-[10px] uppercase tracking-wider text-amber-700 dark:text-amber-400">
                        {s.warning}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>

            <p className="text-[11px] italic text-muted-foreground">
              {plan.disclaimer}
            </p>
          </div>
        )}
      </div>
    </section>
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

  const onDrop = React.useCallback(
    (files: File[]) => {
      const file = files[0];
      if (!file) return;
      importer.mutate(
        { broker, file },
        {
          onSuccess: (res) => {
            const msg = `${broker}: imported ${res.imported}, rejected ${res.rejected}`;
            if (res.errors.length) {
              toast.warning(msg + ` · ${res.errors.length} errors`);
            } else {
              toast.success(msg);
            }
          },
          onError: (err) => {
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
        className={`cursor-pointer border border-dashed p-4 text-sm transition-colors ${
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50 hover:bg-accent/30"
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
      {importer.isPending ? (
        // Honest indeterminate bar: fetch() can't report real upload progress,
        // so we show motion tied to the live mutation state rather than a
        // fabricated percentage. Clears the moment the request settles.
        <div
          className="mt-1 h-1 w-full overflow-hidden bg-muted"
          role="progressbar"
          aria-label={`Uploading ${label} CSV`}
        >
          <div className="h-full w-1/3 animate-pulse bg-primary" />
        </div>
      ) : null}
    </div>
  );
}
