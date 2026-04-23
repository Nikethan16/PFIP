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
