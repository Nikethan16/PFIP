"use client";

/**
 * Goals — will I get there?
 *
 * Monte Carlo projection of net worth from a starting corpus + monthly SIP over
 * N years, with percentile outcomes and, against a target, the probability of
 * reaching it plus the monthly contribution needed to hit it at the median.
 * Data: useGoalProjection() → POST /portfolio/goals/project.
 */

import * as React from "react";
import { Target } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { Kpi } from "@/components/shared/kpi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useGoalProjection, type GoalProjection } from "@/lib/api";
import { formatINR } from "@/lib/utils";

export default function GoalsPage() {
  const [corpus, setCorpus] = React.useState("500000");
  const [monthly, setMonthly] = React.useState("25000");
  const [years, setYears] = React.useState("15");
  const [ret, setRet] = React.useState("11");
  const [vol, setVol] = React.useState("15");
  const [target, setTarget] = React.useState("10000000");
  const [autoVol, setAutoVol] = React.useState(false);
  const mutation = useGoalProjection();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const y = Number(years);
    if (!(y > 0)) return;
    mutation.mutate({
      current_corpus_inr: Number(corpus) || 0,
      monthly_contribution_inr: Number(monthly) || 0,
      years: y,
      expected_annual_return: (Number(ret) || 0) / 100,
      annual_volatility: (Number(vol) || 0) / 100,
      target_inr: target ? Number(target) : null,
      vol_source: autoVol ? "auto" : "manual",
    });
  }

  const res = mutation.data;

  return (
    <div className="space-y-6">
      <div className="page-header">
        <div className="eyebrow">Planning // Monte Carlo</div>
        <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">Goals</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Project where your savings land across thousands of simulated market
          paths — and what it takes to reach a target. Advisory; outcomes are a
          distribution, not a promise.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="grid grid-cols-2 gap-4 border border-border/60 bg-card p-5 sm:grid-cols-3 lg:grid-cols-6"
      >
        <Field label="Current corpus ₹" value={corpus} onChange={setCorpus} />
        <Field label="Monthly SIP ₹" value={monthly} onChange={setMonthly} />
        <Field label="Years" value={years} onChange={setYears} />
        <Field label="Return % p.a." value={ret} onChange={setRet} />
        <Field label={autoVol ? "Volatility % (fallback)" : "Volatility %"} value={vol} onChange={setVol} />
        <Field label="Target ₹ (optional)" value={target} onChange={setTarget} />
        <label className="col-span-2 flex items-center gap-2 self-end pb-2 text-xs text-muted-foreground sm:col-span-1">
          <input
            type="checkbox"
            checked={autoVol}
            onChange={(e) => setAutoVol(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          Auto vol (NIFTY history)
        </label>
        <Button
          type="submit"
          disabled={mutation.isPending}
          className="col-span-2 self-end sm:col-span-1"
        >
          {mutation.isPending ? "Projecting…" : "Project"}
        </Button>
      </form>

      {mutation.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(mutation.error as Error).message}
        </div>
      ) : !res ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={Target}
            title="Set up a projection"
            description="Enter your corpus, monthly SIP, horizon and assumptions to see the range of outcomes."
          />
        </section>
      ) : (
        <GoalResultView res={res} />
      )}
    </div>
  );
}

function GoalResultView({ res }: { res: GoalProjection }) {
  const prob = res.probability_of_target;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Kpi label="Median outcome" value={formatINR(res.percentiles_inr.p50)} hint="50th percentile" />
        <Kpi label="Expected" value={formatINR(res.expected_inr)} hint="mean of sims" />
        <Kpi label="Total invested" value={formatINR(res.total_contributed_inr)} hint={`${res.n_months} months`} />
        {prob != null ? (
          <Kpi
            label="Reach target"
            value={`${(prob * 100).toFixed(0)}%`}
            valueClassName={prob >= 0.7 ? "text-emerald-600 dark:text-emerald-400" : prob >= 0.4 ? "" : "text-destructive"}
            hint={res.target_inr ? formatINR(res.target_inr) : undefined}
            accent
          />
        ) : null}
      </div>

      {res.vol_source ? (
        <p className="text-xs text-muted-foreground">
          Volatility used:{" "}
          <span className="font-mono">
            {(((res.annual_volatility_used ?? res.annual_volatility) || 0) * 100).toFixed(1)}%
          </span>{" "}
          · source:{" "}
          <span className="font-medium text-foreground">
            {res.vol_source === "historical"
              ? "NIFTY realised vol"
              : res.vol_source === "chronos"
                ? "Chronos model"
                : res.vol_source === "manual_fallback"
                  ? "manual (no market data)"
                  : "manual"}
          </span>
        </p>
      ) : null}

      <section className="border border-border/60 bg-card p-5">
        <div className="eyebrow">Outcome distribution</div>
        <div className="mt-3 space-y-2">
          {(
            [
              ["Pessimistic (P10)", res.percentiles_inr.p10],
              ["P25", res.percentiles_inr.p25],
              ["Median (P50)", res.percentiles_inr.p50],
              ["P75", res.percentiles_inr.p75],
              ["Optimistic (P90)", res.percentiles_inr.p90],
            ] as const
          ).map(([label, value]) => {
            const max = res.percentiles_inr.p90 || 1;
            return (
              <div key={label}>
                <div className="mb-1 flex items-baseline justify-between text-sm">
                  <span className="font-label text-xs uppercase tracking-wider text-muted-foreground">{label}</span>
                  <span className="font-mono tabular-nums">{formatINR(value)}</span>
                </div>
                <div className="h-2 w-full overflow-hidden bg-secondary/40">
                  <div className="h-full bg-primary" style={{ width: `${Math.min(100, (value / max) * 100)}%` }} />
                </div>
              </div>
            );
          })}
        </div>
        {res.required_monthly_contribution_inr != null ? (
          <p className="mt-4 border-t border-border/40 pt-3 text-sm">
            To hit your target at the median, invest{" "}
            <span className="font-mono font-semibold">
              {formatINR(res.required_monthly_contribution_inr)}
            </span>{" "}
            per month.
          </p>
        ) : null}
        {res.disclaimer ? (
          <p className="mt-2 text-[11px] text-muted-foreground">{res.disclaimer}</p>
        ) : null}
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </Label>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="decimal"
        className="font-mono"
      />
    </div>
  );
}
