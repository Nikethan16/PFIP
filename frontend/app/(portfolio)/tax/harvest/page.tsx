"use client";

/**
 * Tax · Loss harvesting page.
 *
 * Wraps `POST /api/v1/tax/harvest`. The user supplies the realized
 * gains they've already booked this FY (so the engine can compute
 * exact offset savings), the system pulls open lots from `holdings`
 * and returns a ranked plan.
 *
 * Honors Indian tax rules:
 * - VDA / crypto excluded (Section 115BBH — no loss set-off).
 * - LTCG savings honor the ₹1L exemption (engine math fixed
 *   2026-05-30; see `tests/test_tax_harvest.py`).
 * - Suggestions within 30 days of FY end carry a re-buy warning.
 */

import * as React from "react";
import { AlertTriangle, Calculator, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";

/** Human label for a harvest-skip reason code from the backend. */
function reasonLabel(reason: string): string {
  if (reason === "vda_no_setoff") return "crypto/VDA — no loss set-off allowed (§115BBH)";
  if (reason === "no_price") return "no current price to mark against";
  if (reason.startsWith("category:")) return `unsupported category (${reason.slice(9)})`;
  return reason;
}
import { PageHeader } from "@/components/shared/page-header";
import { useHarvestPlan, type HarvestSuggestion } from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";

function currentFy(): string {
  // Indian FY runs April–March. FY 2026-27 = April 2026 – March 2027.
  const d = new Date();
  const yr = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${yr}-${String((yr + 1) % 100).padStart(2, "0")}`;
}

export default function TaxHarvestPage() {
  const harvest = useHarvestPlan();

  const [fy, setFy] = React.useState<string>(currentFy());
  const [stcg, setStcg] = React.useState<number>(0);
  const [ltcg, setLtcg] = React.useState<number>(0);
  const [debt, setDebt] = React.useState<number>(0);
  const [slab, setSlab] = React.useState<number>(0.3);
  const [surcharge, setSurcharge] = React.useState<number>(0);

  const onRun = () => {
    harvest.mutate({
      fy,
      realised_stcg_equity_inr: stcg,
      realised_ltcg_equity_inr: ltcg,
      realised_debt_gain_inr: debt,
      marginal_slab_rate: slab,
      surcharge_rate: surcharge,
    });
  };

  const plan = harvest.data;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Tax · Loss harvesting"
        description="Rank open lots whose realized loss would meaningfully offset existing gains this FY. Indian rules baked in. Crypto excluded by law."
      />

      {/* Inputs grid */}
      <div className="rounded-lg border bg-card p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Field label="FY">
            <Input value={fy} onChange={(e) => setFy(e.target.value)} placeholder="2026-27" />
          </Field>
          <Field label="Realised STCG (INR)">
            <Input
              type="number"
              value={stcg}
              onChange={(e) => setStcg(parseFloat(e.target.value) || 0)}
            />
          </Field>
          <Field label="Realised LTCG (INR)">
            <Input
              type="number"
              value={ltcg}
              onChange={(e) => setLtcg(parseFloat(e.target.value) || 0)}
            />
          </Field>
          <Field label="Realised debt-MF (INR)">
            <Input
              type="number"
              value={debt}
              onChange={(e) => setDebt(parseFloat(e.target.value) || 0)}
            />
          </Field>
          <Field label="Marginal slab rate (0–1)">
            <Input
              type="number"
              step="0.01"
              value={slab}
              onChange={(e) => setSlab(parseFloat(e.target.value) || 0)}
            />
          </Field>
          <Field label="Surcharge rate (0–1)">
            <Input
              type="number"
              step="0.01"
              value={surcharge}
              onChange={(e) => setSurcharge(parseFloat(e.target.value) || 0)}
            />
          </Field>
        </div>
        <div className="mt-3 flex items-center justify-end gap-2">
          <Button onClick={onRun} size="sm" disabled={harvest.isPending} className="gap-2">
            {harvest.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Calculator className="h-3.5 w-3.5" />
            )}
            {harvest.isPending ? "Computing…" : "Run harvest"}
          </Button>
        </div>
      </div>

      {/* Result section */}
      {harvest.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : harvest.error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t compute harvest plan: {(harvest.error as Error).message}
        </div>
      ) : plan ? (
        <>
          <SummaryStrip plan={plan} />
          {plan.suggestions.length === 0 ? (
            <div className="space-y-2">
              <EmptyState
                title="No worthwhile harvest this FY"
                description="Either no open lots are at a loss, or harvesting them wouldn't offset enough realized gains to be worth it. Re-run after the next loss-making close."
              />
              {plan.skipped && plan.skipped.length ? (
                <div className="border border-border/60 bg-card p-4 text-xs text-muted-foreground">
                  <div className="mb-1 font-medium text-foreground">
                    Holdings not considered ({plan.skipped.length})
                  </div>
                  <ul className="space-y-0.5">
                    {plan.skipped.map((s, i) => (
                      <li key={i}>
                        <span className="font-mono">{s.symbol}</span> — {reasonLabel(s.reason)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : (
            <SuggestionsTable suggestions={plan.suggestions} />
          )}
          <DisclaimerCard text={plan.disclaimer} />
        </>
      ) : (
        <EmptyState
          title="Enter your realized gains to start"
          description="The engine needs to know what you've already booked this FY (STCG, LTCG, debt-MF) to compute the offset value of each open loss."
        />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function SummaryStrip({
  plan,
}: {
  plan: { total_loss_inr: string; total_tax_saved_inr: string; n_lots_evaluated: number; fy: string };
}) {
  const totalLoss = Number(plan.total_loss_inr) || 0;
  const totalSaved = Number(plan.total_tax_saved_inr) || 0;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <SummaryTile label={`Lots evaluated · FY ${plan.fy}`} value={plan.n_lots_evaluated.toString()} />
      <SummaryTile
        label="Total harvestable loss"
        value={formatINR(totalLoss)}
        tone="negative"
      />
      <SummaryTile
        label="Estimated tax saved"
        value={formatINR(totalSaved)}
        tone="positive"
      />
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-2 font-mono text-2xl font-semibold tabular-nums",
          tone === "positive" && "text-emerald-600 dark:text-emerald-400",
          tone === "negative" && "text-red-600 dark:text-red-400",
          !tone && "text-foreground",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function SuggestionsTable({ suggestions }: { suggestions: HarvestSuggestion[] }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Symbol</th>
            <th className="px-3 py-2 text-left font-medium">Class</th>
            <th className="px-3 py-2 text-left font-medium">Term</th>
            <th className="px-3 py-2 text-right font-medium">Qty</th>
            <th className="px-3 py-2 text-right font-medium">Loss (INR)</th>
            <th className="px-3 py-2 text-right font-medium">Tax saved</th>
            <th className="px-3 py-2 text-left font-medium">Offsets</th>
            <th className="px-3 py-2 text-left font-medium">Flag</th>
          </tr>
        </thead>
        <tbody>
          {suggestions.map((s) => {
            const saved = Number(s.estimated_tax_saved_inr) || 0;
            const loss = Number(s.loss_inr) || 0;
            return (
              <tr key={s.lot_id} className="border-t hover:bg-accent/40 transition-colors">
                <td className="px-3 py-2 font-mono text-xs">{s.symbol}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{s.asset_class}</td>
                <td className="px-3 py-2 text-xs">
                  <span
                    className={cn(
                      "rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
                      s.term === "STCG"
                        ? "border-amber-500/40 text-amber-600 dark:text-amber-400"
                        : "border-emerald-500/40 text-emerald-600 dark:text-emerald-400",
                    )}
                  >
                    {s.term}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{s.qty}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-red-600 dark:text-red-400">
                  {formatINR(loss)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-emerald-600 dark:text-emerald-400">
                  {formatINR(saved)}
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{s.offsets_against}</td>
                <td className="px-3 py-2">
                  {s.warning ? (
                    <span
                      title={s.warning}
                      className="inline-flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400 cursor-help"
                    >
                      <AlertTriangle className="h-3 w-3" />
                      Re-buy risk
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DisclaimerCard({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300">
      <strong>Disclaimer:</strong> {text}
    </div>
  );
}
