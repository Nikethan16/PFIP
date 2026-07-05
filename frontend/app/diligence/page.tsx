"use client";

/**
 * Sahara "Due Diligence" — the per-asset research dossier.
 *
 * A read-only research surface that stitches together everything the platform
 * knows about a single asset: live price, fundamentals, regulatory filings,
 * insider / PIT disclosures, market-wide FII/DII flows, on-chain stats (crypto),
 * the model's regime + (experimental) signal read, recent news, and an
 * auto-generated coverage summary.
 *
 * Data mapping (every value traces to the real /diligence/{symbol} envelope —
 * no fabrication; sections degrade to {}/[]/null and are gated on presence):
 *   - dossier            ← useDiligence(symbol)   (/diligence/{symbol})
 *   - symbol picker       ← useWatchlist()         (/watchlist) for suggestions
 *
 * Deep-linkable: `?symbol=NVDA` loads that asset directly, so other pages
 * (e.g. the watchlist row) can link straight into a dossier.
 *
 * ADVISORY-ONLY: this is automated research aggregation, NOT investment advice.
 * There are no buy/sell affordances. The model read is badged EXPERIMENTAL and
 * the summary's disclaimer is shown prominently. The single action is
 * "Ask the agent for a full report", which opens the chat agent.
 */

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Bitcoin,
  Building2,
  CircleDollarSign,
  Clock,
  ExternalLink,
  FileText,
  FlaskConical,
  Landmark,
  LineChart,
  type LucideIcon,
  Minus,
  Newspaper,
  ScanSearch,
  Search,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { PeerTable } from "@/components/shared/peer-table";
import { openAgentChat } from "@/components/chat/chat-widget";
import {
  useDiligence,
  useWatchlist,
  type DiligenceDossier,
  type DiligenceFlowLeg,
  type DiligenceModelRead,
} from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

// A small default roster so the picker has something useful even before the
// watchlist resolves (and so a bare `/diligence` visit shows a real dossier).
const FALLBACK_SYMBOLS = [
  "NVDA",
  "AAPL",
  "MSFT",
  "RELIANCE.NS",
  "BTC-USD",
  "ETH-USD",
];

// =============================================================================
// Page shell — Suspense boundary so `useSearchParams` can read `?symbol=`.
// =============================================================================

export default function DiligencePage() {
  return (
    <React.Suspense fallback={<DossierSkeleton />}>
      <DiligencePageInner />
    </React.Suspense>
  );
}

function DiligencePageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const urlSymbol = params.get("symbol")?.trim() ?? "";

  const { data: watchlist } = useWatchlist();

  // Candidate symbols for the picker: watchlist first, then the fallbacks,
  // de-duped (case-insensitive), preserving order.
  const candidates = React.useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of [
      ...(watchlist ?? []).map((w) => w.symbol),
      ...FALLBACK_SYMBOLS,
    ]) {
      const up = s.toUpperCase();
      if (!seen.has(up)) {
        seen.add(up);
        out.push(s);
      }
    }
    return out;
  }, [watchlist]);

  // The active symbol is driven by the URL so the page stays deep-linkable and
  // back/forward works. When the URL has no `?symbol=`, default to the first
  // candidate once it's known.
  const active = urlSymbol || candidates[0] || "";

  const setSymbol = React.useCallback(
    (symbol: string) => {
      const sym = symbol.trim();
      if (!sym) return;
      // Shallow URL update; typedRoutes is off so a string href is fine.
      router.push(`/diligence?symbol=${encodeURIComponent(sym)}` as never);
    },
    [router],
  );

  const { data, isLoading, error, isError } = useDiligence(active);
  // A 404 (unknown symbol) is an expected "no data" state, not a hard error.
  const notFound = isError && error?.status === 404;

  return (
    <div className="space-y-6">
      {/* Header — serif "Due Diligence" + advisory eyebrow + symbol picker. */}
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow flex items-center gap-2">
            Research // per-asset dossier · advisory only
          </div>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">
            Due Diligence
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            A single research view per asset — fundamentals, filings, flows,
            on-chain, the model read and the news around it. Automated
            aggregation for research, never a recommendation.
          </p>
        </div>
        <SymbolPicker
          value={active}
          candidates={candidates}
          onSelect={setSymbol}
        />
      </div>

      {!active ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={ScanSearch}
            title="Pick a symbol to research"
            description="Search any ticker (NVDA, RELIANCE.NS, BTC-USD) to pull its full dossier."
          />
        </section>
      ) : isLoading ? (
        <DossierSkeleton />
      ) : notFound ? (
        <section className="border border-border/60 bg-card">
          <EmptyState
            icon={ScanSearch}
            title={`No data for ${active} yet`}
            description="This symbol isn't known to the platform, or its research sources haven't ingested it. Add it to your watchlist to begin tracking, or try a different ticker."
            action={{ label: "Go to watchlist", href: "/watchlist" }}
          />
        </section>
      ) : isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Couldn&apos;t load the dossier for {active}: {error?.message}
        </div>
      ) : data ? (
        <Dossier dossier={data} />
      ) : null}
    </div>
  );
}

// =============================================================================
// Symbol picker — a tiny searchable selector (datalist) + a few quick chips.
// =============================================================================

function SymbolPicker({
  value,
  candidates,
  onSelect,
}: {
  value: string;
  candidates: string[];
  onSelect: (s: string) => void;
}) {
  const [draft, setDraft] = React.useState(value);

  // Keep the input in sync when the active symbol changes from elsewhere
  // (deep link, quick chip, back/forward).
  React.useEffect(() => {
    setDraft(value);
  }, [value]);

  const submit = () => {
    const sym = draft.trim().toUpperCase();
    if (sym) onSelect(sym);
  };

  // A short quick-pick strip of the first few candidates (excluding the active).
  const quick = candidates
    .filter((c) => c.toUpperCase() !== value.toUpperCase())
    .slice(0, 4);

  return (
    <div className="w-full sm:w-auto">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex items-center gap-2"
        role="search"
        aria-label="Research a symbol"
      >
        <div className="relative flex-1 sm:w-64">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Search symbol — NVDA, RELIANCE.NS…"
            aria-label="Symbol"
            list="pfip-diligence-symbols"
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            className="h-9 w-full border border-input bg-background pl-8 pr-3 font-mono text-sm uppercase ring-offset-background placeholder:font-sans placeholder:normal-case placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <datalist id="pfip-diligence-symbols">
            {candidates.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>
        <button
          type="submit"
          className="inline-flex h-9 items-center gap-1.5 bg-primary px-3 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
        >
          <ScanSearch className="h-3.5 w-3.5" />
          Research
        </button>
      </form>
      {quick.length ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground/70">
            Quick
          </span>
          {quick.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onSelect(c)}
              className="border border-border/70 px-2 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary hover:text-primary"
            >
              {c}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// =============================================================================
// Dossier — the full research view for one resolved symbol.
// =============================================================================

function Dossier({ dossier: d }: { dossier: DiligenceDossier }) {
  const isCrypto = d.asset_class === "crypto";
  const isIndia = d.market === "NSE" || d.market === "BSE";
  const flows = d.institutional_flows;
  const hasFlows = !!(flows && (flows.fii || flows.dii));
  const onchainEntries = Object.entries(d.onchain ?? {});

  return (
    <div className="space-y-5">
      <DossierHeader dossier={d} />

      {/* Ask the agent — the single (advisory) action on the page. */}
      <AskAgentBar symbol={d.symbol} />

      {/* Key metrics — only the curated key_metrics that exist for this source. */}
      <KeyMetrics dossier={d} />

      {/* Peer comparison — renders only when a curated peer group + metrics exist. */}
      <PeerTable symbol={d.symbol} />

      {/* Model read — regime + experimental signal. */}
      {d.model_read ? <ModelRead read={d.model_read} /> : null}

      {/* Two-column body: filings/news on the left, flows/on-chain on the right
          on wide screens. Each section self-gates on data presence. */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Filings filings={d.filings} symbol={d.symbol} />
        <NewsList news={d.news} symbol={d.symbol} />
        {isIndia || hasFlows ? <Flows flows={flows} /> : null}
        {isCrypto || onchainEntries.length ? (
          <OnChain entries={onchainEntries} />
        ) : null}
        <Insider rows={d.insider} />
      </div>

      {/* Summary + prominent disclaimer. */}
      <SummaryBlock summary={d.summary} />
    </div>
  );
}

// --- Header ------------------------------------------------------------------

/** Crude asset → category sub-label + icon, mirroring signal-card's heuristic. */
function assetMeta(d: DiligenceDossier): { category: string; Icon: LucideIcon } {
  if (d.asset_class === "crypto") return { category: "Crypto · spot", Icon: Bitcoin };
  if (d.market === "NSE" || d.market === "BSE")
    return { category: "India equity", Icon: LineChart };
  if (d.asset_class === "equity") return { category: "Equity · cash", Icon: LineChart };
  if (d.asset_class === "fx") return { category: "FX pair", Icon: CircleDollarSign };
  return { category: d.asset_class ?? "Asset", Icon: LineChart };
}

function DossierHeader({ dossier: d }: { dossier: DiligenceDossier }) {
  const { category, Icon } = assetMeta(d);
  const change = d.change_pct;
  const positive = (change ?? 0) >= 0;
  const Trend = change == null ? Minus : positive ? TrendingUp : TrendingDown;
  const tone =
    change == null
      ? "text-muted-foreground"
      : positive
        ? "text-emerald-700 dark:text-emerald-400"
        : "text-red-700 dark:text-red-400";

  return (
    <section className="border border-border/60 bg-card">
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center border border-border/60 bg-secondary/40">
            <Icon className="h-6 w-6 text-foreground" aria-hidden />
          </div>
          <div className="min-w-0">
            <h2 className="truncate font-serif text-2xl leading-none tracking-tight sm:text-3xl">
              {d.symbol}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span className="eyebrow">{category}</span>
              {d.market ? <Chip>{d.market}</Chip> : null}
              {d.asset_class ? <Chip>{d.asset_class}</Chip> : null}
            </div>
          </div>
        </div>

        {/* Last price + change */}
        <div className="sm:text-right">
          <div className="font-mono text-3xl font-semibold tabular-nums">
            {d.last_price != null ? (
              <Price value={d.last_price} dossier={d} />
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
          <div
            className={cn(
              "mt-1 flex items-center gap-1.5 font-mono text-sm font-semibold tabular-nums sm:justify-end",
              tone,
            )}
          >
            <Trend className="h-3.5 w-3.5" />
            {d.change != null ? (
              <span>
                {d.change >= 0 ? "+" : ""}
                {d.change.toFixed(2)}
              </span>
            ) : null}
            {change != null ? (
              <span>
                ({change >= 0 ? "+" : ""}
                {change.toFixed(2)}%)
              </span>
            ) : (
              <span className="text-muted-foreground">no change data</span>
            )}
          </div>
          <div className="mt-1 font-mono text-[11px] text-muted-foreground">
            {d.price_as_of
              ? `Price as of ${formatIST(d.price_as_of, "dd MMM yyyy")}`
              : null}
          </div>
        </div>
      </div>

      {/* Footer strip — dossier as-of timestamp. */}
      <div className="flex items-center gap-1.5 border-t border-border/40 bg-secondary/20 px-5 py-2 font-mono text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3" aria-hidden />
        Dossier compiled {d.as_of ? formatIST(d.as_of, "dd MMM yyyy HH:mm 'IST'") : "—"}
      </div>
    </section>
  );
}

/** Render a price with a currency hint inferred from the asset's market. */
function Price({
  value,
  dossier: d,
}: {
  value: number;
  dossier: DiligenceDossier;
}) {
  const inr = d.market === "NSE" || d.market === "BSE";
  const symbol = inr ? "₹" : "$";
  return (
    <span>
      <span className="text-foreground/50">{symbol}</span>
      {value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}
    </span>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center border border-border/60 bg-secondary/40 px-1.5 py-0.5 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
      {children}
    </span>
  );
}

// --- Ask the agent -----------------------------------------------------------

function AskAgentBar({ symbol }: { symbol: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border border-primary/30 bg-primary/5 p-4">
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-primary/40 bg-primary/10 text-primary">
          <Sparkles className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">
            Want the narrative?
          </div>
          <div className="text-xs text-muted-foreground">
            Have the agent synthesise this dossier into a written report.
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={() => openAgentChat(`Do a full due diligence on ${symbol}`)}
        className="inline-flex items-center gap-1.5 bg-primary px-3.5 py-2 font-label text-xs uppercase tracking-wider text-primary-foreground transition-all hover:brightness-110"
      >
        <Sparkles className="h-3.5 w-3.5" />
        Ask the agent for a full report
      </button>
    </div>
  );
}

// --- Key metrics -------------------------------------------------------------

// Curated metric keys we know how to label + format, in display order. We only
// render the ones present in `fundamentals.key_metrics` (source-dependent), so
// crypto (2 keys) and India screener (~7) degrade naturally vs finnhub (~18).
interface MetricDef {
  key: string;
  label: string;
  kind: "ratio" | "pct" | "pct100" | "money" | "price" | "raw";
}

const METRIC_DEFS: MetricDef[] = [
  { key: "pe_ratio", label: "P / E", kind: "ratio" },
  { key: "pb_ratio", label: "P / B", kind: "ratio" },
  { key: "price_to_sales", label: "P / S", kind: "ratio" },
  { key: "gross_margin", label: "Gross margin", kind: "pct100" },
  { key: "operating_margin", label: "Operating margin", kind: "pct100" },
  { key: "net_margin", label: "Net margin", kind: "pct100" },
  { key: "roe", label: "ROE", kind: "pct100" },
  { key: "roa", label: "ROA", kind: "pct100" },
  { key: "roce", label: "ROCE", kind: "pct100" },
  { key: "revenue_growth", label: "Revenue growth", kind: "pct100" },
  { key: "eps_growth", label: "EPS growth", kind: "pct100" },
  { key: "debt_to_equity", label: "Debt / equity", kind: "ratio" },
  { key: "current_ratio", label: "Current ratio", kind: "ratio" },
  { key: "market_cap", label: "Market cap", kind: "money" },
  { key: "dividend_yield", label: "Dividend yield", kind: "pct" },
  { key: "beta", label: "Beta", kind: "ratio" },
  { key: "book_value", label: "Book value", kind: "price" },
  { key: "current_price", label: "Current price", kind: "price" },
];

function KeyMetrics({ dossier: d }: { dossier: DiligenceDossier }) {
  const f = d.fundamentals;
  const km = f?.key_metrics ?? {};
  const inr = d.market === "NSE" || d.market === "BSE";

  // Build the ordered list of present metrics, then append the 52-week range
  // (which lives as two separate keys) as a single combined cell.
  const cells = React.useMemo(() => {
    const out: Array<{ label: string; value: string }> = [];
    for (const def of METRIC_DEFS) {
      const raw = km[def.key];
      if (raw == null || raw === "") continue;
      const num = typeof raw === "number" ? raw : Number(raw);
      if (Number.isNaN(num)) {
        out.push({ label: def.label, value: String(raw) });
        continue;
      }
      out.push({ label: def.label, value: formatMetric(num, def.kind, inr) });
    }
    // 52-week range — finnhub exposes it as 52w_high / 52w_low.
    const hi = km["52w_high"];
    const lo = km["52w_low"];
    if (hi != null && lo != null) {
      const cur = inr ? "₹" : "$";
      out.push({
        label: "52-week range",
        value: `${cur}${fmtCompact(Number(lo))} – ${cur}${fmtCompact(Number(hi))}`,
      });
    }
    return out;
  }, [km, inr]);

  if (!f || !cells.length) {
    return (
      <Panel title="Key metrics" eyebrow="Fundamentals">
        <EmptyNote>
          No fundamentals on file for this asset yet.
        </EmptyNote>
      </Panel>
    );
  }

  return (
    <Panel
      title="Key metrics"
      eyebrow="Fundamentals"
      meta={
        f.source || f.as_of_date
          ? `${f.source ?? "source"}${f.as_of_date ? ` · ${formatIST(f.as_of_date, "dd MMM yyyy")}` : ""}`
          : undefined
      }
    >
      <div className="grid grid-cols-2 gap-px overflow-hidden border border-border/50 bg-border/50 sm:grid-cols-3 lg:grid-cols-4">
        {cells.map((c) => (
          <div key={c.label} className="bg-card p-3">
            <div className="eyebrow truncate" title={c.label}>
              {c.label}
            </div>
            <div className="mt-0.5 font-mono text-base font-semibold tabular-nums">
              {c.value}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// --- Model read --------------------------------------------------------------

const DIRECTION_TONE: Record<string, string> = {
  BUY: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
  SELL: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40",
  HOLD: "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/40",
};

function ModelRead({ read }: { read: DiligenceModelRead }) {
  const regime = read.regime;
  const signal = read.signal;
  const dir = signal?.direction?.toUpperCase() ?? "HOLD";
  const DirIcon =
    dir === "BUY" ? TrendingUp : dir === "SELL" ? TrendingDown : Minus;

  return (
    <Panel title="Model read" eyebrow="Regime + signal">
      {/* Experimental caveat leads — this is model output, not advice. */}
      <div className="mb-3">
        <ExperimentalBadge />
      </div>

      <div className="grid grid-cols-1 gap-px overflow-hidden border border-border/50 bg-border/50 sm:grid-cols-2">
        {/* Regime */}
        <div className="bg-card p-4">
          <div className="eyebrow">Current regime</div>
          {regime ? (
            <>
              <div className="mt-1 font-serif text-xl tracking-tight">
                {humaniseRegime(regime.label)}
              </div>
              {regime.confidence != null ? (
                <ConfidenceLine
                  label="Confidence"
                  value={Math.round(regime.confidence * 100)}
                />
              ) : null}
              {regime.since ? (
                <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                  since {formatIST(regime.since, "dd MMM HH:mm 'IST'")}
                </div>
              ) : null}
            </>
          ) : (
            <div className="mt-1 text-sm text-muted-foreground">
              No regime classified.
            </div>
          )}
        </div>

        {/* Signal */}
        <div className="bg-card p-4">
          <div className="eyebrow">Latest signal</div>
          {signal ? (
            <>
              <div className="mt-1.5 flex items-center gap-2">
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-label text-[11px] font-semibold uppercase tracking-widest",
                    DIRECTION_TONE[dir] ?? DIRECTION_TONE.HOLD,
                  )}
                >
                  <DirIcon className="h-3 w-3" />
                  {dir}
                </span>
                {signal.horizon_hours != null ? (
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {signal.horizon_hours}h horizon
                  </span>
                ) : null}
              </div>
              {signal.confidence != null ? (
                <ConfidenceLine label="Confidence" value={signal.confidence} />
              ) : null}
              <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                {signal.model ? `${signal.model}` : ""}
                {signal.generated_at
                  ? ` · ${formatIST(signal.generated_at, "dd MMM HH:mm 'IST'")}`
                  : ""}
              </div>
            </>
          ) : (
            <div className="mt-1 text-sm text-muted-foreground">
              No signal generated for this asset.
            </div>
          )}
        </div>
      </div>

      {read.disclaimer ? (
        <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600 dark:text-amber-400" />
          {read.disclaimer}
        </p>
      ) : null}
    </Panel>
  );
}

function ConfidenceLine({ label, value }: { label: string; value: number }) {
  const width = Math.min(100, Math.max(0, value));
  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <span className="font-mono text-xs font-semibold tabular-nums">
          {value}%
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden bg-muted"
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(width)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full bg-primary transition-all duration-500"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

/** Amber "Experimental" chip — same treatment as signal-card.tsx. */
const EXPERIMENTAL_TOOLTIP =
  "Model read is experimental — not investment advice. Confidence reflects model certainty, not realized accuracy.";

function ExperimentalBadge() {
  return (
    <span
      className="group/exp relative inline-flex cursor-help items-center gap-1 border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-label text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-700 dark:text-amber-300"
      tabIndex={0}
      role="note"
      aria-label={EXPERIMENTAL_TOOLTIP}
      title={EXPERIMENTAL_TOOLTIP}
    >
      <FlaskConical className="h-3 w-3" aria-hidden />
      Experimental
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-[calc(100%+6px)] z-30 hidden w-64 border border-border/70 bg-popover p-2.5 text-[11px] font-normal normal-case leading-relaxed tracking-normal text-muted-foreground shadow-md group-hover/exp:block group-focus/exp:block"
      >
        {EXPERIMENTAL_TOOLTIP}
      </span>
    </span>
  );
}

// --- Filings -----------------------------------------------------------------

function Filings({
  filings,
  symbol,
}: {
  filings: DiligenceDossier["filings"];
  symbol: string;
}) {
  return (
    <Panel
      title="Filings & announcements"
      eyebrow="Disclosures"
      icon={FileText}
      meta={filings.length ? `${filings.length} recent` : undefined}
    >
      {!filings.length ? (
        <EmptyNote>No filings on file for {symbol}.</EmptyNote>
      ) : (
        <ol className="relative space-y-0">
          {filings.slice(0, 12).map((f, i) => {
            const inner = (
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm text-foreground group-hover/filing:text-primary">
                    {f.title}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                    {f.type ? <span>{f.type.replace(/_/g, " ")}</span> : null}
                    {f.source ? <span>· {f.source.replace(/_/g, " ")}</span> : null}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {f.date ? (
                    <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                      {formatIST(f.date, "dd MMM yyyy")}
                    </span>
                  ) : null}
                  {f.url ? (
                    <ExternalLink className="h-3 w-3 text-muted-foreground/60 group-hover/filing:text-primary" />
                  ) : null}
                </div>
              </div>
            );
            return (
              <li
                key={`${f.url ?? f.title}-${i}`}
                className="border-b border-border/30 last:border-b-0"
              >
                {f.url ? (
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group/filing block py-2.5 transition-colors"
                  >
                    {inner}
                  </a>
                ) : (
                  <div className="group/filing block py-2.5">{inner}</div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

// --- News --------------------------------------------------------------------

function NewsList({
  news,
  symbol,
}: {
  news: DiligenceDossier["news"];
  symbol: string;
}) {
  return (
    <Panel
      title="Recent news"
      eyebrow="Market intelligence"
      icon={Newspaper}
      meta={news.length ? `${news.length} item${news.length === 1 ? "" : "s"}` : undefined}
    >
      {!news.length ? (
        <EmptyNote>No recent headlines for {symbol}.</EmptyNote>
      ) : (
        <ul className="space-y-0">
          {news.slice(0, 10).map((n, i) => {
            const inner = (
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="line-clamp-2 text-sm text-foreground group-hover/news:text-primary">
                    {n.title}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2">
                    {n.source ? (
                      <span className="font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                        {n.source}
                      </span>
                    ) : null}
                    <SentimentChip value={n.sentiment} />
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {n.time ? (
                    <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                      {formatIST(n.time, "dd MMM")}
                    </span>
                  ) : null}
                  {n.url ? (
                    <ExternalLink className="h-3 w-3 text-muted-foreground/60 group-hover/news:text-primary" />
                  ) : null}
                </div>
              </div>
            );
            return (
              <li
                key={`${n.url ?? n.title}-${i}`}
                className="border-b border-border/30 last:border-b-0"
              >
                {n.url ? (
                  <a
                    href={n.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group/news block py-2.5 transition-colors"
                  >
                    {inner}
                  </a>
                ) : (
                  <div className="group/news block py-2.5">{inner}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

/** Sentiment → labelled chip. The feed scores roughly in [-1, 1]. */
function SentimentChip({ value }: { value: number | null }) {
  if (value == null) return null;
  const tone =
    value > 0.05
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : value < -0.05
        ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300"
        : "border-border/60 bg-secondary/40 text-muted-foreground";
  const label =
    value > 0.05 ? "Positive" : value < -0.05 ? "Negative" : "Neutral";
  return (
    <span
      className={cn(
        "inline-flex items-center border px-1.5 py-0 font-label text-[9px] uppercase tracking-wider",
        tone,
      )}
      title={`Sentiment score ${value.toFixed(2)}`}
    >
      {label}
    </span>
  );
}

// --- Institutional flows (India) --------------------------------------------

function Flows({
  flows,
}: {
  flows: DiligenceDossier["institutional_flows"];
}) {
  const unit = flows.unit ?? "INR crore";
  return (
    <Panel
      title="Institutional flows"
      eyebrow="Market-wide FII / DII"
      icon={Landmark}
      meta={flows.as_of_date ? formatIST(flows.as_of_date, "dd MMM yyyy") : undefined}
    >
      <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground">
        Whole-market foreign (FII) and domestic (DII) institutional cash flow for
        the session — a breadth gauge, not specific to this symbol. Values in{" "}
        {unit}.
      </p>
      <div className="space-y-3">
        <FlowRow label="FII (foreign)" leg={flows.fii ?? null} />
        <FlowRow label="DII (domestic)" leg={flows.dii ?? null} />
      </div>
    </Panel>
  );
}

function FlowRow({ label, leg }: { label: string; leg: DiligenceFlowLeg | null }) {
  if (!leg) {
    return (
      <div className="border border-border/40 p-3">
        <div className="eyebrow">{label}</div>
        <div className="mt-1 text-sm text-muted-foreground">No data.</div>
      </div>
    );
  }
  const net = leg.netValue;
  const positive = (net ?? 0) >= 0;
  const netTone =
    net == null
      ? "text-muted-foreground"
      : positive
        ? "text-emerald-700 dark:text-emerald-400"
        : "text-red-700 dark:text-red-400";
  return (
    <div className="border border-border/40 p-3">
      <div className="flex items-center justify-between">
        <div className="eyebrow">{label}</div>
        <div className={cn("font-mono text-sm font-semibold tabular-nums", netTone)}>
          {net == null ? "—" : `${net >= 0 ? "+" : ""}${fmtCompact(net)}`}
          <span className="ml-1 font-label text-[9px] uppercase tracking-wider text-muted-foreground">
            net
          </span>
        </div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-center">
        <div className="bg-secondary/30 p-1.5">
          <div className="font-label text-[9px] uppercase tracking-wider text-muted-foreground">
            Buy
          </div>
          <div className="font-mono text-xs font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
            {leg.buyValue == null ? "—" : fmtCompact(leg.buyValue)}
          </div>
        </div>
        <div className="bg-secondary/30 p-1.5">
          <div className="font-label text-[9px] uppercase tracking-wider text-muted-foreground">
            Sell
          </div>
          <div className="font-mono text-xs font-semibold tabular-nums text-red-700 dark:text-red-400">
            {leg.sellValue == null ? "—" : fmtCompact(leg.sellValue)}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- On-chain (crypto) -------------------------------------------------------

// Friendly labels + formatting for the on-chain blob keys we recognise. Unknown
// keys still render with a humanised label and a sensible numeric format.
const ONCHAIN_DEFS: Record<
  string,
  { label: string; kind: "money" | "pct" | "fee" | "hashrate" | "int" | "raw" }
> = {
  market_cap_usd: { label: "Market cap", kind: "money" },
  volume_24h_usd: { label: "24h volume", kind: "money" },
  price_usd: { label: "Price (USD)", kind: "money" },
  dominance_pct: { label: "Dominance", kind: "pct" },
  hashrate_3d: { label: "Hashrate (3d)", kind: "hashrate" },
  fastestFee: { label: "Fastest fee", kind: "fee" },
  halfHourFee: { label: "½-hour fee", kind: "fee" },
  hourFee: { label: "1-hour fee", kind: "fee" },
  economyFee: { label: "Economy fee", kind: "fee" },
  minimumFee: { label: "Minimum fee", kind: "fee" },
  count: { label: "Mempool tx", kind: "int" },
  vsize: { label: "Mempool vsize", kind: "int" },
  total_fee: { label: "Mempool fees", kind: "int" },
  chain_tip_height: { label: "Block height", kind: "int" },
};

const ONCHAIN_ORDER = [
  "price_usd",
  "market_cap_usd",
  "volume_24h_usd",
  "dominance_pct",
  "hashrate_3d",
  "chain_tip_height",
  "count",
  "vsize",
  "total_fee",
  "fastestFee",
  "halfHourFee",
  "hourFee",
  "economyFee",
  "minimumFee",
];

function OnChain({ entries }: { entries: Array<[string, number | string | null]> }) {
  const cells = React.useMemo(() => {
    const map = new Map(entries);
    const orderedKeys = [
      ...ONCHAIN_ORDER.filter((k) => map.has(k)),
      ...[...map.keys()].filter((k) => !ONCHAIN_ORDER.includes(k)),
    ];
    return orderedKeys
      .map((k) => {
        const raw = map.get(k);
        if (raw == null || raw === "") return null;
        const def = ONCHAIN_DEFS[k];
        const num = typeof raw === "number" ? raw : Number(raw);
        const value = Number.isNaN(num)
          ? String(raw)
          : formatOnchain(num, def?.kind ?? "raw");
        return { label: def?.label ?? humaniseKey(k), value };
      })
      .filter((x): x is { label: string; value: string } => x !== null);
  }, [entries]);

  return (
    <Panel title="On-chain" eyebrow="Network stats" icon={Bitcoin}>
      {!cells.length ? (
        <EmptyNote>No on-chain metrics available.</EmptyNote>
      ) : (
        <div className="grid grid-cols-2 gap-px overflow-hidden border border-border/50 bg-border/50">
          {cells.map((c) => (
            <div key={c.label} className="bg-card p-3">
              <div className="eyebrow truncate" title={c.label}>
                {c.label}
              </div>
              <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums">
                {c.value}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

// --- Insider -----------------------------------------------------------------

function Insider({ rows }: { rows: DiligenceDossier["insider"] }) {
  if (!rows.length) {
    // Insider data is sparse; only render the panel when there's something to
    // show so the grid doesn't carry an empty card for most assets.
    return null;
  }
  return (
    <Panel title="Insider activity" eyebrow="PIT disclosures" icon={Users}>
      <ul className="space-y-0">
        {rows.slice(0, 10).map((r, i) => {
          const name = strField(r, ["name", "person", "acquirer"]);
          const txn = strField(r, ["transaction", "type", "mode"]);
          const date = strField(r, ["date", "time"]);
          const shares = numField(r, ["shares", "quantity", "qty"]);
          const value = numField(r, ["value", "amount"]);
          return (
            <li
              key={i}
              className="flex items-start justify-between gap-3 border-b border-border/30 py-2.5 last:border-b-0"
            >
              <div className="min-w-0">
                <div className="truncate text-sm text-foreground">
                  {name ?? "Insider"}
                </div>
                <div className="mt-0.5 font-label text-[10px] uppercase tracking-wider text-muted-foreground">
                  {txn ?? "transaction"}
                  {shares != null ? ` · ${fmtCompact(shares)} sh` : ""}
                </div>
              </div>
              <div className="shrink-0 text-right">
                {value != null ? (
                  <div className="font-mono text-xs font-semibold tabular-nums">
                    {fmtCompact(value)}
                  </div>
                ) : null}
                {date ? (
                  <div className="font-mono text-[11px] text-muted-foreground">
                    {formatIST(date, "dd MMM yyyy")}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

// --- Summary -----------------------------------------------------------------

function SummaryBlock({
  summary,
}: {
  summary: DiligenceDossier["summary"];
}) {
  if (!summary) return null;
  return (
    <section className="border border-border/60 bg-card">
      <div className="flex items-center gap-2 border-b border-border/40 p-5">
        <Building2 className="h-4 w-4 text-muted-foreground" aria-hidden />
        <div>
          <div className="eyebrow">Coverage summary</div>
          <h3 className="mt-0.5 font-serif text-xl tracking-tight">
            What we have on this asset
          </h3>
        </div>
      </div>
      <div className="space-y-4 p-5">
        {summary.data_coverage ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {summary.data_coverage}
          </p>
        ) : null}

        {summary.annotations.length ? (
          <ul className="space-y-1.5">
            {summary.annotations.map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/50" />
                <span className="text-foreground/90">{a}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {/* Disclaimer — prominent, advisory framing. */}
        {summary.disclaimer ? (
          <div className="flex items-start gap-2 border border-amber-500/30 bg-amber-500/5 p-3.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-xs leading-relaxed text-foreground/80">
              {summary.disclaimer}
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

// =============================================================================
// Shared layout primitives + formatting helpers
// =============================================================================

function Panel({
  title,
  eyebrow,
  icon: Icon,
  meta,
  children,
}: {
  title: string;
  eyebrow: string;
  icon?: LucideIcon;
  meta?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-border/60 bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-border/40 p-4">
        <div className="flex items-center gap-2">
          {Icon ? (
            <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
          ) : null}
          <div>
            <div className="eyebrow">{eyebrow}</div>
            <h3 className="mt-0.5 font-serif text-lg tracking-tight">{title}</h3>
          </div>
        </div>
        {meta ? (
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">
            {meta}
          </span>
        ) : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-dashed border-border/60 p-4 text-center text-[12px] text-muted-foreground">
      {children}
    </div>
  );
}

function DossierSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-44 w-full" />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    </div>
  );
}

// --- Number / label formatting ----------------------------------------------

function humaniseKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const REGIME_LABELS: Record<string, string> = {
  bull_trend: "Bull trend",
  bear_trend: "Bear trend",
  sideways: "Range-bound",
  high_volatility: "High volatility",
  accumulation: "Accumulation",
  distribution: "Distribution",
};

function humaniseRegime(label: string): string {
  return REGIME_LABELS[label] ?? humaniseKey(label);
}

/** Compact large numbers: 4_963_420 → "4.96M", 1.21e12 → "1.21T". */
function fmtCompact(n: number): string {
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  if (abs < 1 && abs > 0) return n.toFixed(4);
  return n.toFixed(2);
}

function formatMetric(
  n: number,
  kind: MetricDef["kind"],
  inr: boolean,
): string {
  const cur = inr ? "₹" : "$";
  switch (kind) {
    case "ratio":
      return `${n.toFixed(2)}×`;
    case "pct100":
      // Already a percentage number (e.g. 74.15 → "74.2%").
      return `${n.toFixed(2)}%`;
    case "pct":
      // A small ratio that represents a percent yield. Some sources report
      // dividend yield as a fraction (0.0196) and some as a percent (0.46).
      // Show as-is with a % — the value's source unit is preserved.
      return `${n.toFixed(2)}%`;
    case "money":
      return `${cur}${fmtCompact(n)}`;
    case "price":
      return `${cur}${n.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    case "raw":
    default:
      return fmtCompact(n);
  }
}

function formatOnchain(
  n: number,
  kind: "money" | "pct" | "fee" | "hashrate" | "int" | "raw",
): string {
  switch (kind) {
    case "money":
      return `$${fmtCompact(n)}`;
    case "pct":
      return `${n.toFixed(2)}%`;
    case "fee":
      return `${n.toFixed(0)} sat/vB`;
    case "hashrate":
      // Hashrate arrives in raw H/s; show in EH/s (1e18) for Bitcoin scale.
      return `${(n / 1e18).toFixed(2)} EH/s`;
    case "int":
      return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
    case "raw":
    default:
      return fmtCompact(n);
  }
}

// --- Tolerant field readers for the dynamic insider rows ---------------------

function strField(
  row: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "string" && v.trim()) return v;
    if (typeof v === "number") return String(v);
  }
  return null;
}

function numField(
  row: Record<string, unknown>,
  keys: string[],
): number | null {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "number" && !Number.isNaN(v)) return v;
    if (typeof v === "string") {
      const n = Number(v.replace(/[, ]/g, ""));
      if (!Number.isNaN(n)) return n;
    }
  }
  return null;
}
