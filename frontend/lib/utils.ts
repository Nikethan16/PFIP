import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { formatInTimeZone } from "date-fns-tz";

/**
 * Compose Tailwind class names safely.
 * Keeps conditional classes working and resolves conflicts (e.g. `p-2 p-4`).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** User-facing timezone. All display timestamps are rendered as IST. */
export const DISPLAY_TZ = "Asia/Kolkata";

/** Format an ISO-8601 UTC timestamp for display in IST. */
export function formatIST(iso: string | Date, pattern = "dd MMM yyyy HH:mm 'IST'"): string {
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return formatInTimeZone(d, DISPLAY_TZ, pattern);
}

/** Short date, e.g. "21 Apr". */
export function formatISTDate(iso: string | Date): string {
  return formatIST(iso, "dd MMM");
}

/** Indian Rupees formatter. Uses the en-IN locale's lakh/crore grouping. */
export function formatINR(value: number | null | undefined, fractionDigits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Percentage with signed prefix; positive values show a leading "+". */
export function formatPct(value: number | null | undefined, fractionDigits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(fractionDigits)}%`;
}

/** Clamp a numeric confidence (0-100) into a Tremor-friendly color bucket. */
export function confidenceTone(confidence: number): "red" | "amber" | "emerald" {
  if (confidence >= 70) return "emerald";
  if (confidence >= 45) return "amber";
  return "red";
}

/** USD currency, for US-denominated figures shown alongside INR ones. */
export function formatUSD(value: number | null | undefined, fractionDigits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Compact magnitude (1.2T / 340M / 5.1K) — for market caps, revenue, volume. */
export function formatCompact(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(digits)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(digits)}K`;
  return value.toFixed(0);
}

/** Tailwind text-colour class for a signed P&L / return value. */
export function pnlToneClass(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return "text-muted-foreground";
  return value > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";
}

/** "as of <date>" freshness bucket from an ISO timestamp + a staleness SLA. */
export function freshnessOf(
  iso: string | null | undefined,
  staleAfterDays = 4,
): { asOf: string; stale: boolean; ageDays: number | null } {
  if (!iso) return { asOf: "—", stale: true, ageDays: null };
  const d = new Date(iso);
  const ageDays = (Date.now() - d.getTime()) / 86_400_000;
  return { asOf: d.toISOString().slice(0, 10), stale: ageDays > staleAfterDays, ageDays };
}
