"use client";

import * as React from "react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { usePerspectives } from "@/lib/api";

const PERSONA_LABEL: Record<string, string> = {
  value: "Value investor",
  macro: "Macro strategist",
  risk: "Risk manager",
};

export default function PerspectivesPage() {
  const [q, setQ] = React.useState("");
  const ask = usePerspectives();

  const onAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim()) ask.mutate({ question: q.trim() });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Perspectives"
        description="Ask one question, get three independent expert lenses — value, macro, and risk. Distinct views for your own judgement, never a single verdict. Advisory only."
      />

      <form onSubmit={onAsk} className="space-y-3 border border-border/60 bg-card p-5">
        <Textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. Is now a good time to add to Indian IT, or wait?"
          rows={3}
          aria-label="Question"
        />
        <Button type="submit" disabled={ask.isPending || !q.trim()}>
          {ask.isPending ? "Consulting the panel…" : "Ask the panel"}
        </Button>
      </form>

      {ask.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(ask.error as Error).message}
        </div>
      ) : ask.data ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            {ask.data.perspectives.map((p) => (
              <div key={p.persona} className="border border-border/60 bg-card p-4">
                <div className="eyebrow mb-2">{PERSONA_LABEL[p.persona] ?? p.persona}</div>
                <p className="text-sm leading-relaxed">{p.view}</p>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">{ask.data.disclaimer}</p>
        </div>
      ) : null}
    </div>
  );
}
