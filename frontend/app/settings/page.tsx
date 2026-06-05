"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { PageHeader } from "@/components/shared/page-header";
import { SourceHealthPanel } from "@/components/settings/source-health-panel";
import { toast } from "@/components/ui/toast";
import {
  useUpdateUserSettings,
  useUserSettings,
  type UserSettings,
} from "@/lib/api";
import { formatIST } from "@/lib/utils";

type FormShape = UserSettings;

/**
 * Settings backed by `/settings`.
 *   - Risk limits editor
 *   - Tax year selection
 *   - Alert preferences (severity threshold, quiet hours)
 *   - Model registry: default per regime + last calibration
 *   - Scheduled Prefect deployments: active flag + last run
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
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load settings: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Risk limits, tax year, alert preferences, model registry, scheduled tasks."
        actions={
          <Button onClick={onSave} disabled={update.isPending} size="sm">
            {update.isPending ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…
              </span>
            ) : (
              "Save changes"
            )}
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Risk limits</CardTitle>
          <CardDescription>
            Hard caps for new positions and drawdown halt. PFIP refuses to
            generate BUY signals once these trip.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <Label htmlFor="max-pos">Max position (%)</Label>
            <Input
              id="max-pos"
              type="number"
              value={form.max_position_pct}
              onChange={(e) =>
                patch("max_position_pct", Number(e.target.value))
              }
            />
          </div>
          <div>
            <Label htmlFor="dd-halt">Drawdown halt (%)</Label>
            <Input
              id="dd-halt"
              type="number"
              value={form.drawdown_halt_pct}
              onChange={(e) =>
                patch("drawdown_halt_pct", Number(e.target.value))
              }
            />
          </div>
          <div>
            <Label htmlFor="daily-cap">New positions / day</Label>
            <Input
              id="daily-cap"
              type="number"
              value={form.daily_new_positions_cap}
              onChange={(e) =>
                patch("daily_new_positions_cap", Number(e.target.value))
              }
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tax</CardTitle>
          <CardDescription>India FY — runs April to March.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <Label htmlFor="fy">Financial year</Label>
            <Input
              id="fy"
              placeholder="2026-27"
              value={form.tax_year}
              onChange={(e) => patch("tax_year", e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Alerts</CardTitle>
          <CardDescription>
            Choose how PFIP reaches you outside the app.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="severity">Minimum severity</Label>
              <Select
                value={form.alert_severity_threshold}
                onValueChange={(v) => patch("alert_severity_threshold", v)}
              >
                <SelectTrigger id="severity">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="info">Info</SelectItem>
                  <SelectItem value="warning">Warning</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="quiet-start">Quiet hours start</Label>
              <Input
                id="quiet-start"
                type="time"
                value={form.quiet_hours_start}
                onChange={(e) => patch("quiet_hours_start", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="quiet-end">Quiet hours end</Label>
              <Input
                id="quiet-end"
                type="time"
                value={form.quiet_hours_end}
                onChange={(e) => patch("quiet_hours_end", e.target.value)}
              />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <div className="font-medium">Morning brief</div>
              <div className="text-xs text-muted-foreground">
                Daily digest at 08:00 IST.
              </div>
            </div>
            <Switch
              checked={form.morning_brief_enabled}
              onCheckedChange={(v) => patch("morning_brief_enabled", Boolean(v))}
            />
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <div className="font-medium">Telegram alerts</div>
              <div className="text-xs text-muted-foreground">
                Requires TELEGRAM_BOT_TOKEN in .env. Off by default.
              </div>
            </div>
            <Switch
              checked={form.telegram_alerts_enabled}
              onCheckedChange={(v) =>
                patch("telegram_alerts_enabled", Boolean(v))
              }
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Model registry</CardTitle>
          <CardDescription>
            Which model is currently default per regime. Changes here flow to
            the signal pipeline on the next run.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {Object.keys(form.default_models_by_regime).length === 0 ? (
            <EmptyState
              title="No models registered yet"
              description="Train and register a model in the backend to see it here."
            />
          ) : (
            <ul className="space-y-2 text-sm">
              {Object.entries(form.default_models_by_regime).map(
                ([regime, info]) => (
                  <li
                    key={regime}
                    className="flex items-center justify-between rounded-md border p-2"
                  >
                    <div>
                      <div className="font-medium">
                        {regime.replace(/_/g, " ")}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {info.name}
                      </div>
                    </div>
                    <Badge variant="outline">v{info.version}</Badge>
                  </li>
                ),
              )}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scheduled tasks</CardTitle>
          <CardDescription>
            Prefect deployments: active flag + last successful run.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!form.scheduled_tasks.length ? (
            <EmptyState
              title="No scheduled deployments"
              description="Register a Prefect deployment (e.g. morning-brief, daily-ingest) to see it listed here."
            />
          ) : (
            <ul className="space-y-2 text-sm">
              {form.scheduled_tasks.map((t) => (
                <li
                  key={t.deployment}
                  className="flex items-center justify-between rounded-md border p-2"
                >
                  <div>
                    <div className="font-mono text-xs">{t.deployment}</div>
                    <div className="text-[11px] text-muted-foreground">
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Source health</CardTitle>
          <CardDescription>
            Per-adapter ingest status, updated every 60s. Filter to failing
            adapters when troubleshooting; the runbooks in{" "}
            <code>docs/runbooks/</code> cover the recurring failure modes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SourceHealthPanel />
        </CardContent>
      </Card>

      <div className="sticky bottom-4 z-10 flex justify-end">
        <div className="rounded-lg border bg-background/95 px-3 py-2 shadow-lg backdrop-blur">
          <Button onClick={onSave} disabled={update.isPending} size="sm">
            {update.isPending ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…
              </span>
            ) : (
              "Save settings"
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
