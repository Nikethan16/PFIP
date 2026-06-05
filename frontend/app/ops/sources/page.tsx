"use client";

/**
 * Operations · Source health — dedicated page for the ingest health
 * monitor. The same `<SourceHealthPanel>` is also embedded on the
 * Settings page; this route gives it first-class navigation so the
 * "Source health" item in the Operations sidebar group lands on its
 * own URL rather than hash-jumping inside Settings.
 *
 * Matches §8.10 of `docs/FRONTEND_DESIGN_PROMPT.md` — four KPI tiles
 * up top + dense table + per-row error drawer.
 */

import { PageHeader } from "@/components/shared/page-header";
import { SourceHealthPanel } from "@/components/settings/source-health-panel";

export default function OpsSourcesPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Source health"
        description="Per-ingest-adapter freshness. Auto-refreshes every 60 seconds. Failing rows page Telegram if the kill switch is off."
      />
      <SourceHealthPanel />
    </div>
  );
}
