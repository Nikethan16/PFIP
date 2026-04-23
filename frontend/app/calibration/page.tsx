"use client";

import * as React from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { ReliabilityCard } from "@/components/calibration/reliability-card";
import { EmptyState } from "@/components/shared/empty-state";
import { useCalibration, useCalibrationHistory } from "@/lib/api";

export default function CalibrationPage() {
  const { data, isLoading, error } = useCalibration();
  const { data: history } = useCalibrationHistory();

  const historyByKey = React.useMemo(() => {
    const map = new Map<string, (typeof history)[number]>();
    (history ?? []).forEach((h) =>
      map.set(`${h.model_name}@${h.model_version}`, h),
    );
    return map;
  }, [history]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Calibration</h1>
        <p className="text-sm text-muted-foreground">
          Brier, ECE, and sharpness per model with reliability curves.
          Lower is better. Models flagged red if ECE &gt; 0.15 for 2 months in
          a row (auto-suspended).
        </p>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-96 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load calibration: {(error as Error).message}
        </div>
      ) : !data?.length ? (
        <EmptyState
          title="No calibration reports yet"
          description="Train a signal model in the backend to generate one. New reports appear after each run."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data.map((rpt) => (
            <ReliabilityCard
              key={`${rpt.model_name}-${rpt.model_version}`}
              report={rpt}
              history={historyByKey.get(
                `${rpt.model_name}@${rpt.model_version}`,
              )}
            />
          ))}
        </div>
      )}
    </div>
  );
}
