"use client";

/**
 * Welcome / first-run modal. Auto-shows on the dashboard when
 * `GET /api/v1/setup/status` returns `needs_setup=true`. Offers three
 * tracks the user can choose between:
 *
 *   1. **Bootstrap real data** — seeds the default watchlist + runs the
 *      free ingest flows (AMFI / FX / macro / crypto). Takes 2–4 min.
 *   2. **Seed demo data** — synthetic OHLCV / news / regime / holdings
 *      so the dashboard renders end-to-end without external API calls.
 *   3. **I'll do it later** — dismisses; suppressed for the rest of
 *      this session via `localStorage`.
 *
 * Idempotent. Re-showing on every refresh until either path completes
 * or the user opts out.
 */

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Sparkles,
  Database,
  ArrowRight,
  X,
} from "lucide-react";

import {
  useBootstrap,
  useSeedDemo,
  useSetupStatus,
} from "@/lib/api";

const DISMISS_KEY = "pfip:welcome-dismissed";

export function WelcomeModal() {
  const status = useSetupStatus({ refetchInterval: 15_000 });
  const bootstrap = useBootstrap();
  const seedDemo = useSeedDemo();
  const [dismissed, setDismissed] = useState(false);
  const [stepLog, setStepLog] = useState<string[]>([]);

  // Read dismiss flag once on mount (avoids SSR mismatch).
  useEffect(() => {
    if (typeof window !== "undefined") {
      setDismissed(window.localStorage.getItem(DISMISS_KEY) === "1");
    }
  }, []);

  const shouldShow =
    !dismissed && !status.isLoading && status.data?.needs_setup === true;

  if (!shouldShow) return null;

  const handleBootstrap = async () => {
    setStepLog(["⏳ Seeding watchlist…"]);
    try {
      const result = await bootstrap.mutateAsync();
      const lines = result.steps.map((s) =>
        s.ok
          ? `✅ ${s.step}${s.rows != null ? ` (${s.rows.toLocaleString()} rows)` : s.added != null ? ` (${s.added} added)` : ""}`
          : `⚠️ ${s.step} — ${s.error ?? "failed"}`,
      );
      setStepLog(lines);
    } catch (err) {
      setStepLog([`❌ Bootstrap failed: ${(err as Error).message}`]);
    }
  };

  const handleDemo = async () => {
    setStepLog(["⏳ Seeding demo data…"]);
    try {
      const result = await seedDemo.mutateAsync();
      const lines = Object.entries(result.counts).map(
        ([table, n]) => `✅ ${table}: ${n} synthetic rows`,
      );
      setStepLog(lines);
    } catch (err) {
      setStepLog([`❌ Demo seed failed: ${(err as Error).message}`]);
    }
  };

  const handleDismiss = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DISMISS_KEY, "1");
    }
    setDismissed(true);
  };

  const busy = bootstrap.isPending || seedDemo.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
    >
      <div className="relative max-w-2xl w-full mx-4 rounded-xl border border-border bg-card text-card-foreground shadow-2xl">
        <button
          type="button"
          onClick={handleDismiss}
          className="absolute right-4 top-4 text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Dismiss welcome"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="p-6 sm:p-8">
          <div className="flex items-center gap-3 mb-2">
            <Sparkles className="h-6 w-6 text-yellow-500" />
            <span className="text-xs uppercase tracking-wider text-muted-foreground">
              First-run setup
            </span>
          </div>
          <h2 className="text-2xl font-semibold mb-2">
            Welcome to PFIP
          </h2>
          <p className="text-sm text-muted-foreground mb-6">
            The dashboard is empty because no data has been ingested yet. Pick a track:
          </p>

          {/* Option A — bootstrap real data */}
          <div className="rounded-lg border border-border p-4 mb-3 hover:border-foreground/30 transition-colors">
            <div className="flex items-start gap-3">
              <Database className="h-5 w-5 text-green-500 mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="font-medium flex items-center justify-between">
                  <span>Bootstrap real data</span>
                  <span className="text-xs text-muted-foreground">2–4 min</span>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  Seed a default watchlist (5 tickers per market) and run the free
                  ingest flows: AMFI NAVs, FX rates, macro series, crypto OHLCV.
                  Recommended for actual use.
                </p>
                <button
                  type="button"
                  onClick={handleBootstrap}
                  disabled={busy}
                  className="mt-3 inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
                >
                  {bootstrap.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <ArrowRight className="h-4 w-4" />
                  )}
                  {bootstrap.isPending ? "Running…" : "Start bootstrap"}
                </button>
              </div>
            </div>
          </div>

          {/* Option B — demo data */}
          <div className="rounded-lg border border-border p-4 mb-3 hover:border-foreground/30 transition-colors">
            <div className="flex items-start gap-3">
              <Sparkles className="h-5 w-5 text-yellow-500 mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="font-medium flex items-center justify-between">
                  <span>Seed demo data</span>
                  <span className="text-xs text-muted-foreground">~5 sec</span>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  Fill every page with realistic synthetic samples (90 days of
                  OHLCV, mock holdings, signals, news). Lets you exercise the
                  whole UI without API calls. Remove via Settings later.
                </p>
                <button
                  type="button"
                  onClick={handleDemo}
                  disabled={busy}
                  className="mt-3 inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-50 transition"
                >
                  {seedDemo.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <ArrowRight className="h-4 w-4" />
                  )}
                  {seedDemo.isPending ? "Seeding…" : "Seed demo data"}
                </button>
              </div>
            </div>
          </div>

          {/* Option C — dismiss */}
          <div className="rounded-lg border border-border p-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="h-5 w-5 text-muted-foreground mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="font-medium">I&apos;ll set this up via PowerShell later</div>
                <p className="text-sm text-muted-foreground mt-1">
                  Suppress this modal for this session. See <code>docs/runbooks/</code>
                  and the seed scripts in <code>backend/pfip/scripts/</code>.
                </p>
                <button
                  type="button"
                  onClick={handleDismiss}
                  disabled={busy}
                  className="mt-3 text-sm text-muted-foreground hover:text-foreground underline underline-offset-2"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>

          {/* Step log */}
          {stepLog.length > 0 && (
            <div className="mt-5 rounded-md border border-border bg-muted/30 p-3 text-xs font-mono">
              {stepLog.map((line, i) => (
                <div key={i} className="py-0.5">
                  {line}
                </div>
              ))}
            </div>
          )}

          <p className="mt-5 text-xs text-muted-foreground">
            Either path is reversible. Demo data is removed via{" "}
            <code>DELETE /api/v1/setup/demo</code>; real ingest data persists in
            TimescaleDB and is removed only by truncating tables.
          </p>
        </div>
      </div>
    </div>
  );
}
