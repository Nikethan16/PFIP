"use client";

/**
 * SIP — what a monthly plan grows to.
 *
 * Projects the future corpus of a monthly SIP at an assumed return (future
 * value of a monthly annuity, compounded monthly). Data: useSipProjection() →
 * POST /portfolio/sip/project. Advisory.
 */

import * as React from "react";
import { PiggyBank } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { Kpi } from "@/components/shared/kpi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSipProjection } from "@/lib/api";
import { formatINR } from "@/lib/utils";

export default function SipPage() {
  const [monthly, setMonthly] = React.useState("10000");
  const [years, setYears] = React.useState("10");
  const [ret, setRet] = React.useState("12");
  const [corpus, setCorpus] = React.useState("0");
  const mutation = useSipProjection();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const y = Number(years);
    if (y < 0) return;
    mutation.mutate({
      monthly_amount_inr: Number(monthly) || 0,
      years: y,
      annual_return: (Number(ret) || 0) / 100,
      current_corpus_inr: Number(corpus) || 0,
    });
  }

  const res = mutation.data;

  return (
    <div className="space-y-6">
      <div className="page-header">
        <div className="eyebrow">Planning // SIP</div>
        <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">SIP Projection</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Project the corpus a monthly Systematic Investment Plan grows to. The
          XIRR of an existing SIP is available via the API; this view models a
          forward plan.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="grid grid-cols-2 gap-4 border border-border/60 bg-card p-5 sm:grid-cols-5"
      >
        <Field label="Monthly ₹" value={monthly} onChange={setMonthly} />
        <Field label="Years" value={years} onChange={setYears} />
        <Field label="Return % p.a." value={ret} onChange={setRet} />
        <Field label="Existing corpus ₹" value={corpus} onChange={setCorpus} />
        <Button type="submit" disabled={mutation.isPending} className="self-end">
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
            icon={PiggyBank}
            title="Project a SIP"
            description="Enter a monthly amount, horizon and assumed return to see the projected corpus and total gain."
          />
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Kpi label="Projected corpus" value={formatINR(res.projected_corpus_inr)} hint={`${res.months} months`} accent valueClassName="text-primary" />
          <Kpi label="Total invested" value={formatINR(res.total_invested_inr)} hint="your contributions" />
          <Kpi label="Wealth gained" value={formatINR(res.gain_inr)} hint="compounding" valueClassName="text-emerald-600 dark:text-emerald-400" />
        </div>
      )}
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
