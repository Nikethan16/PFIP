"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/shared/empty-state";
import { SourceHealthPanel } from "@/components/settings/source-health-panel";
import { toast } from "@/components/ui/toast";
import {
  useUpdateUserSettings,
  useUserSettings,
  type UserSettings,
} from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

type FormShape = UserSettings;

/**
 * Settings backed by `/settings` — "Sahara" institutional terminal styling.
 *   - Risk limits editor
 *   - Tax year selection
 *   - Alert preferences (severity threshold, quiet hours)
 *   - Model registry: default per regime + last calibration
 *   - Scheduled Prefect deployments: active flag + last run
 *   - Source health panel
 */
export default function SettingsPage() {
  const { data, isLoading, error } = useUserSettings();
  const update = useUpdateUserSettings();

  const [form, setForm] = React.useState<FormShape | null>(null);

  React.useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const patch = <K extends keyof FormShape>(key: K, value: FormShape[K]) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const onSave = async () => {
    if (!form) return;
    try {
      await update.mutateAsync(form);
      toast.success("Settings saved");
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  if (isLoading || !form) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-40" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load settings: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header — serif "Settings" editorial banner + save action. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow">Configuration // advisory engine</div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Settings
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Risk limits, tax year, alert preferences, model registry, scheduled
            tasks.
          </p>
        </div>
        <SaveButton pending={update.isPending} onSave={onSave} label="Save changes" />
      </div>

      <Section
        eyebrow="Risk limits"
        title="Position & drawdown caps"
        description="Hard caps for new positions and drawdown halt. PFIP refuses to generate BUY signals once these trip."
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field htmlFor="max-pos" label="Max position (%)">
            <Input
              id="max-pos"
              type="number"
              value={form.max_position_pct}
              onChange={(e) => patch("max_position_pct", Number(e.target.value))}
              className="mt-1 font-mono tabular-nums"
            />
          </Field>
          <Field htmlFor="dd-halt" label="Drawdown halt (%)">
            <Input
              id="dd-halt"
              type="number"
              value={form.drawdown_halt_pct}
              onChange={(e) =>
                patch("drawdown_halt_pct", Number(e.target.value))
              }
              className="mt-1 font-mono tabular-nums"
            />
          </Field>
          <Field htmlFor="daily-cap" label="New positions / day">
            <Input
              id="daily-cap"
              type="number"
              value={form.daily_new_positions_cap}
              onChange={(e) =>
                patch("daily_new_positions_cap", Number(e.target.value))
              }
              className="mt-1 font-mono tabular-nums"
            />
          </Field>
        </div>
      </Section>

      <Section
        eyebrow="Tax"
        title="Financial year"
        description="India FY — runs April to March."
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field htmlFor="fy" label="Financial year">
            <Input
              id="fy"
              placeholder="2026-27"
              value={form.tax_year}
              onChange={(e) => patch("tax_year", e.target.value)}
              className="mt-1 font-mono"
            />
          </Field>
        </div>
      </Section>

      <Section
        eyebrow="Alerts"
        title="Delivery & quiet hours"
        description="Choose how PFIP reaches you outside the app."
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field htmlFor="severity" label="Minimum severity">
              <Select
                value={form.alert_severity_threshold}
                onValueChange={(v) => patch("alert_severity_threshold", v)}
              >
                <SelectTrigger id="severity" className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="info">Info</SelectItem>
                  <SelectItem value="warning">Warning</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field htmlFor="quiet-start" label="Quiet hours start">
              <Input
                id="quiet-start"
                type="time"
                value={form.quiet_hours_start}
                onChange={(e) => patch("quiet_hours_start", e.target.value)}
                className="mt-1 font-mono"
              />
            </Field>
            <Field htmlFor="quiet-end" label="Quiet hours end">
              <Input
                id="quiet-end"
                type="time"
                value={form.quiet_hours_end}
                onChange={(e) => patch("quiet_hours_end", e.target.value)}
                className="mt-1 font-mono"
              />
            </Field>
          </div>

          <ToggleRow
            title="Morning brief"
            description="Daily digest at 08:00 IST."
            checked={form.morning_brief_enabled}
            onChange={(v) => patch("morning_brief_enabled", v)}
          />
          <ToggleRow
            title="Telegram alerts"
            description="Requires TELEGRAM_BOT_TOKEN in .env. Off by default."
            checked={form.telegram_alerts_enabled}
            onChange={(v) => patch("telegram_alerts_enabled", v)}
          />
        </div>
      </Section>

      <Section
        eyebrow="Model registry"
        title="Default model per regime"
        description="Which model is currently default per regime. Changes here flow to the signal pipeline on the next run."
      >
        {Object.keys(form.default_models_by_regime).length === 0 ? (
          <EmptyState
            title="No models registered yet"
            description="Train and register a model in the backend to see it here."
          />
        ) : (
          <ul className="divide-y divide-border/40 border border-border/50">
            {Object.entries(form.default_models_by_regime).map(
              ([regime, info]) => (
                <li
                  key={regime}
                  className="flex items-center justify-between gap-3 px-4 py-2.5"
                >
                  <div className="min-w-0">
                    <div className="font-label text-xs uppercase tracking-wider">
                      {regime.replace(/_/g, " ")}
                    </div>
                    <div className="truncate font-mono text-[11px] text-muted-foreground">
                      {info.name}
                    </div>
                  </div>
                  <Badge variant="outline" className="font-mono">
                    v{info.version}
                  </Badge>
                </li>
              ),
            )}
          </ul>
        )}
      </Section>

      <Section
        eyebrow="Scheduled tasks"
        title="Prefect deployments"
        description="Active flag + last successful run."
      >
        {!form.scheduled_tasks.length ? (
          <EmptyState
            title="No scheduled deployments"
            description="Register a Prefect deployment (e.g. morning-brief, daily-ingest) to see it listed here."
          />
        ) : (
          <ul className="divide-y divide-border/40 border border-border/50">
            {form.scheduled_tasks.map((t) => (
              <li
                key={t.deployment}
                className="flex items-center justify-between gap-3 px-4 py-2.5"
              >
                <div className="min-w-0">
                  <div className="truncate font-mono text-xs">{t.deployment}</div>
                  <div className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                    Last run:{" "}
                    {t.last_run_at ? formatIST(t.last_run_at) : "never"}
                  </div>
                </div>
                <Badge variant={t.active ? "success" : "secondary"}>
                  {t.active ? "active" : "paused"}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        eyebrow="Source health"
        title="Ingest adapter status"
        description={
          <>
            Per-adapter ingest status, updated every 60s. Filter to failing
            adapters when troubleshooting; the runbooks in{" "}
            <code className="font-mono text-[11px]">docs/runbooks/</code> cover
            the recurring failure modes.
          </>
        }
      >
        <SourceHealthPanel />
      </Section>

      <div className="sticky bottom-4 z-10 flex justify-end">
        <div className="border border-border/70 bg-background/95 px-3 py-2 shadow-lg backdrop-blur">
          <SaveButton pending={update.isPending} onSave={onSave} label="Save settings" />
        </div>
      </div>
    </div>
  );
}

/**
 * Editorial section card — warm border, eyebrow + serif sub-heading header,
 * matching the redesigned dashboard / portfolio pages.
 */
function Section({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-border/60 bg-card">
      <div className="border-b border-border/40 p-5">
        <div className="eyebrow">{eyebrow}</div>
        <h3 className="mt-1 font-serif text-xl tracking-tight">{title}</h3>
        {description ? (
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

/** Uppercase Archivo-Narrow label over a control. */
function Field({
  htmlFor,
  label,
  children,
  className,
}: {
  htmlFor: string;
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <Label htmlFor={htmlFor} className="eyebrow">
        {label}
      </Label>
      {children}
    </div>
  );
}

/** Bordered toggle row (preference switch). */
function ToggleRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between border border-border/50 bg-secondary/30 p-3">
      <div className="min-w-0">
        <div className="font-label text-xs uppercase tracking-wider">
          {title}
        </div>
        <div className="text-[11px] text-muted-foreground">{description}</div>
      </div>
      <Switch checked={checked} onCheckedChange={(v) => onChange(Boolean(v))} />
    </div>
  );
}

/** Shared save button (header + sticky footer), with the in-flight spinner. */
function SaveButton({
  pending,
  onSave,
  label,
}: {
  pending: boolean;
  onSave: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onSave}
      disabled={pending}
      className={cn(
        "inline-flex items-center gap-2 bg-primary px-4 py-2 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110 disabled:opacity-60",
      )}
    >
      {pending ? (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…
        </>
      ) : (
        label
      )}
    </button>
  );
}
