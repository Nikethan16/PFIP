/**
 * Shared display helpers for portfolio holdings — kept in one place so the
 * holdings table and the deep-dive panel label categories + the "company name"
 * subtitle identically.
 *
 * NB: the backend `/portfolio/holdings` payload carries no human company name
 * (only symbol / isin / broker / notes / category). The subtitle therefore
 * prefers the most specific human hint available — notes, then broker, then a
 * humanised category — rather than fabricating a company name.
 */

import type { Holding, HoldingCategory } from "@/lib/contracts";

/** Title-case asset-class labels for each holding category. */
export const CATEGORY_LABELS: Record<HoldingCategory, string> = {
  equity: "Equity",
  etf: "ETF",
  mutual_fund: "Mutual fund",
  ppf: "PPF",
  epf: "EPF",
  nps: "NPS",
  fd: "Fixed deposit",
  sgb: "Sovereign gold",
  gsec: "G-sec",
  bond: "Bond",
  crypto_exchange: "Crypto",
  crypto_self_custody: "Crypto · cold",
  cash: "Cash",
};

/** Short asset-class label for the ASSET CLASS column. */
export function assetClassLabel(category: HoldingCategory): string {
  return CATEGORY_LABELS[category] ?? category;
}

/**
 * The muted "company / category name" rendered under the ticker. Falls back
 * through the available human hints; never invents a company name.
 */
export function holdingDisplayName(h: Holding): string {
  const note = h.notes?.trim();
  if (note) return note;
  if (h.broker) return `${assetClassLabel(h.category)} · ${h.broker}`;
  if (!h.symbol && h.isin) return `${assetClassLabel(h.category)} · ${h.isin}`;
  return assetClassLabel(h.category);
}
