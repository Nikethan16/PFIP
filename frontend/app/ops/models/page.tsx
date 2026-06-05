"use client";

/**
 * Operations · Model registry browser.
 *
 * Lists every model in the file-backed registry (`pfip.signals.registry`).
 * Filter by task / regime / horizon. Pin button writes the
 * `pinned_for[<slot>]` association so the auto-selector uses that
 * artifact for live predictions.
 *
 * Backend: `GET /api/v1/models` + `POST /api/v1/models/{id}/pin`.
 */

import * as React from "react";
import { Pin, PinOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { toast } from "@/components/ui/toast";
import { useModels, usePinModel, type ModelEntry } from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

export default function ModelsPage() {
  const [task, setTask] = React.useState("");
  const [regime, setRegime] = React.useState("");
  const [horizon, setHorizon] = React.useState("");
  const { data, isLoading, error } = useModels({
    task: task || undefined,
    regime: regime || undefined,
    horizon: horizon || undefined,
  });
  const pin = usePinModel();

  const onPin = (m: ModelEntry, slot: string) => {
    pin.mutate(
      { modelId: m.id, slot },
      {
        onSuccess: () => toast.success(`Pinned ${m.name} → ${slot}`),
        onError: (err) => toast.error((err as Error).message),
      },
    );
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Models"
        description="Every model artifact in the file-backed registry. Pin a slot to deploy that model into live signal generation."
      />

      <div className="rounded-lg border bg-card p-3">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
          <Filter label="Task" value={task} onChange={setTask} placeholder="signal" />
          <Filter label="Regime" value={regime} onChange={setRegime} placeholder="bull_trend" />
          <Filter label="Horizon" value={horizon} onChange={setHorizon} placeholder="5d" />
          <div className="flex items-end">
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => {
                setTask("");
                setRegime("");
                setHorizon("");
              }}
            >
              Clear filters
            </Button>
          </div>
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load model registry: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <EmptyState
          title="No models in the registry yet"
          description="Trained models land here automatically when the weekly retraining flow runs (or you can upload via /api/v1/models/upload)."
        />
      ) : (
        <ModelsTable models={data} onPin={onPin} pending={pin.isPending} />
      )}
    </div>
  );
}

function Filter({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </Label>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

function ModelsTable({
  models,
  onPin,
  pending,
}: {
  models: ModelEntry[];
  onPin: (m: ModelEntry, slot: string) => void;
  pending: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Name</th>
            <th className="px-3 py-2 text-left font-medium">Kind</th>
            <th className="px-3 py-2 text-left font-medium">Task</th>
            <th className="px-3 py-2 text-left font-medium">Regime</th>
            <th className="px-3 py-2 text-left font-medium">Horizon</th>
            <th className="px-3 py-2 text-left font-medium">Version</th>
            <th className="px-3 py-2 text-left font-medium">Created</th>
            <th className="px-3 py-2 text-left font-medium">SHA</th>
            <th className="px-3 py-2 text-left font-medium">Pinned</th>
            <th className="px-3 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => {
            const slot = [m.task, m.regime, m.horizon].filter(Boolean).join("/");
            const isPinned = m.pinned_for.length > 0;
            return (
              <tr key={m.id} className="border-t hover:bg-accent/40 transition-colors">
                <td className="px-3 py-2 font-medium">{m.name}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{m.kind}</td>
                <td className="px-3 py-2 text-xs">{m.task}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{m.regime ?? "—"}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{m.horizon ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">{m.version}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {formatIST(m.created_at)}
                </td>
                <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                  {m.sha256.slice(0, 8)}
                </td>
                <td className="px-3 py-2">
                  {isPinned ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-primary">
                      <Pin className="h-3 w-3" /> {m.pinned_for.join(", ")}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <Button
                    size="sm"
                    variant={isPinned ? "outline" : "default"}
                    className={cn("h-7 gap-1 text-xs", isPinned && "text-muted-foreground")}
                    disabled={pending || !slot}
                    onClick={() => onPin(m, slot)}
                  >
                    {isPinned ? (
                      <>
                        <PinOff className="h-3 w-3" /> Repin
                      </>
                    ) : (
                      <>
                        <Pin className="h-3 w-3" /> Pin
                      </>
                    )}
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
