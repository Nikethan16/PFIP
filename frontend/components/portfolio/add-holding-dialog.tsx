"use client";

import * as React from "react";
import { Loader2, Plus } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { useAddHolding, type AddHoldingInput } from "@/lib/api";
import { CATEGORY_LABELS } from "@/components/portfolio/holding-labels";
import { HoldingCategorySchema, type HoldingCategory } from "@/lib/contracts";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/**
 * Manual "Add holding" dialog. Lets someone with PPF / FD / cash (no broker
 * CSV) enter a position by hand. Posts the strict `Holding` body to
 * `POST /api/v1/portfolio/holdings` via `useAddHolding`. Validation mirrors the
 * backend rules (qty > 0, cost basis ≥ 0, fx_rate required for non-INR,
 * self-custody only for crypto) so the user gets inline feedback before the
 * round-trip — this is tracking only, never a trade instruction.
 */

// Ordered list of categories for the select — canonical enum values + labels.
const CATEGORY_ORDER = HoldingCategorySchema.options;

// Crypto categories are the only ones where self-custody is meaningful and the
// only ones the backend permits `is_self_custody=true` for.
const CRYPTO_CATEGORIES = new Set<HoldingCategory>([
  "crypto_exchange",
  "crypto_self_custody",
]);

// Categories that don't have a market ticker — we relax the symbol hint for
// these (cash / PPF / EPF / FD / NPS), and the field stays optional.
const NON_TICKER_CATEGORIES = new Set<HoldingCategory>([
  "ppf",
  "epf",
  "nps",
  "fd",
  "cash",
]);

/** Today's date as YYYY-MM-DD for the date input default. */
function todayISODate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AddHoldingDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const addHolding = useAddHolding();

  const [category, setCategory] = React.useState<HoldingCategory>("equity");
  const [symbol, setSymbol] = React.useState("");
  const [isin, setIsin] = React.useState("");
  const [broker, setBroker] = React.useState("");
  const [qty, setQty] = React.useState("");
  const [costBasis, setCostBasis] = React.useState("");
  const [ccy, setCcy] = React.useState("INR");
  const [fxRate, setFxRate] = React.useState("");
  const [acquiredAt, setAcquiredAt] = React.useState(todayISODate());
  const [isSelfCustody, setIsSelfCustody] = React.useState(false);
  const [notes, setNotes] = React.useState("");

  // Reset the form whenever the dialog closes so re-opening is clean.
  React.useEffect(() => {
    if (!open) {
      setCategory("equity");
      setSymbol("");
      setIsin("");
      setBroker("");
      setQty("");
      setCostBasis("");
      setCcy("INR");
      setFxRate("");
      setAcquiredAt(todayISODate());
      setIsSelfCustody(false);
      setNotes("");
    }
  }, [open]);

  const isCrypto = CRYPTO_CATEGORIES.has(category);
  const isNonTicker = NON_TICKER_CATEGORIES.has(category);
  const ccyUpper = ccy.trim().toUpperCase();
  const needsFx = ccyUpper.length > 0 && ccyUpper !== "INR";

  // When the user switches away from a crypto category, force the self-custody
  // flag off so we never POST an invalid combination.
  React.useEffect(() => {
    if (!isCrypto && isSelfCustody) setIsSelfCustody(false);
  }, [isCrypto, isSelfCustody]);

  // ---- Client-side validation (mirrors PortfolioService._validate) ----------
  const qtyNum = Number(qty);
  const costNum = Number(costBasis);
  const fxNum = Number(fxRate);

  const errors: Partial<Record<string, string>> = {};
  if (qty.trim() === "" || !Number.isFinite(qtyNum)) {
    errors.qty = "Enter a quantity.";
  } else if (qtyNum <= 0) {
    errors.qty = "Quantity must be greater than 0.";
  }
  if (costBasis.trim() === "" || !Number.isFinite(costNum)) {
    errors.costBasis = "Enter the total cost basis in INR.";
  } else if (costNum < 0) {
    errors.costBasis = "Cost basis cannot be negative.";
  }
  if (needsFx && (fxRate.trim() === "" || !Number.isFinite(fxNum) || fxNum <= 0)) {
    errors.fxRate = `FX rate (1 ${ccyUpper} → INR) is required for non-INR cost.`;
  }
  if (!acquiredAt) {
    errors.acquiredAt = "Pick an acquisition date.";
  }
  const valid = Object.keys(errors).length === 0;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    // Send acquired_at as an ISO-8601 timestamp at UTC midnight of the chosen day.
    const acquiredIso = new Date(`${acquiredAt}T00:00:00Z`).toISOString();
    const payload: AddHoldingInput = {
      category,
      qty: qtyNum,
      cost_basis_inr: costNum,
      cost_basis_ccy: ccyUpper || "INR",
      acquired_at: acquiredIso,
      is_self_custody: isCrypto ? isSelfCustody : false,
      symbol: symbol.trim() || null,
      isin: isin.trim() || null,
      broker: broker.trim() || null,
      notes: notes.trim() || null,
      fx_rate: needsFx ? fxNum : null,
    };
    try {
      await addHolding.mutateAsync(payload);
      toast.success("Holding added");
      onOpenChange(false);
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-serif text-xl tracking-tight">
            Add holding
          </DialogTitle>
          <DialogDescription>
            Manually record a position — equity, ETF, mutual fund, PPF / EPF /
            NPS, FD, SGB, G-sec, bonds, cash or crypto. Tracking only; nothing is
            traded.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          {/* Category — native select keeps the dialog dependency-light and
              avoids a nested Radix portal inside the dialog portal. */}
          <div>
            <Label htmlFor="ah-category" className="eyebrow">
              Category
            </Label>
            <select
              id="ah-category"
              value={category}
              onChange={(e) => setCategory(e.target.value as HoldingCategory)}
              className="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              {CATEGORY_ORDER.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABELS[c]}
                </option>
              ))}
            </select>
          </div>

          {/* Symbol + ISIN */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="ah-symbol" className="eyebrow">
                Symbol {isNonTicker ? "(optional)" : ""}
              </Label>
              <Input
                id="ah-symbol"
                placeholder={
                  isCrypto
                    ? "BTC-USD"
                    : isNonTicker
                      ? "—"
                      : "RELIANCE.NS"
                }
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="mt-1 font-mono"
                autoFocus
              />
            </div>
            <div>
              <Label htmlFor="ah-isin" className="eyebrow">
                ISIN (optional)
              </Label>
              <Input
                id="ah-isin"
                placeholder="INE002A01018"
                value={isin}
                onChange={(e) => setIsin(e.target.value)}
                className="mt-1 font-mono"
              />
            </div>
          </div>

          {/* Quantity + cost basis */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="ah-qty" className="eyebrow">
                Quantity / units
              </Label>
              <Input
                id="ah-qty"
                type="number"
                step="any"
                min="0"
                inputMode="decimal"
                placeholder="100"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className={cn(
                  "mt-1 font-mono tabular-nums",
                  errors.qty && "border-destructive",
                )}
                aria-invalid={Boolean(errors.qty)}
              />
              {errors.qty ? (
                <p className="mt-1 text-[11px] text-destructive">{errors.qty}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="ah-cost" className="eyebrow">
                Total cost basis (INR)
              </Label>
              <Input
                id="ah-cost"
                type="number"
                step="any"
                min="0"
                inputMode="decimal"
                placeholder="150000"
                value={costBasis}
                onChange={(e) => setCostBasis(e.target.value)}
                className={cn(
                  "mt-1 font-mono tabular-nums",
                  errors.costBasis && "border-destructive",
                )}
                aria-invalid={Boolean(errors.costBasis)}
              />
              {errors.costBasis ? (
                <p className="mt-1 text-[11px] text-destructive">
                  {errors.costBasis}
                </p>
              ) : null}
            </div>
          </div>

          {/* Currency + FX (FX only required when cost currency ≠ INR) */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="ah-ccy" className="eyebrow">
                Cost currency
              </Label>
              <Input
                id="ah-ccy"
                placeholder="INR"
                value={ccy}
                onChange={(e) => setCcy(e.target.value)}
                className="mt-1 font-mono uppercase"
                maxLength={5}
              />
            </div>
            {needsFx ? (
              <div>
                <Label htmlFor="ah-fx" className="eyebrow">
                  FX rate (1 {ccyUpper} → INR)
                </Label>
                <Input
                  id="ah-fx"
                  type="number"
                  step="any"
                  min="0"
                  inputMode="decimal"
                  placeholder="83.50"
                  value={fxRate}
                  onChange={(e) => setFxRate(e.target.value)}
                  className={cn(
                    "mt-1 font-mono tabular-nums",
                    errors.fxRate && "border-destructive",
                  )}
                  aria-invalid={Boolean(errors.fxRate)}
                />
                {errors.fxRate ? (
                  <p className="mt-1 text-[11px] text-destructive">
                    {errors.fxRate}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          {/* Broker + acquired date */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="ah-broker" className="eyebrow">
                Broker / custodian (optional)
              </Label>
              <Input
                id="ah-broker"
                placeholder="Zerodha"
                value={broker}
                onChange={(e) => setBroker(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="ah-acquired" className="eyebrow">
                Acquired on
              </Label>
              <Input
                id="ah-acquired"
                type="date"
                value={acquiredAt}
                max={todayISODate()}
                onChange={(e) => setAcquiredAt(e.target.value)}
                className={cn(
                  "mt-1 font-mono",
                  errors.acquiredAt && "border-destructive",
                )}
                aria-invalid={Boolean(errors.acquiredAt)}
              />
              {errors.acquiredAt ? (
                <p className="mt-1 text-[11px] text-destructive">
                  {errors.acquiredAt}
                </p>
              ) : null}
            </div>
          </div>

          {/* Self-custody — only relevant + permitted for crypto. */}
          {isCrypto ? (
            <div className="flex items-center justify-between border border-border/50 bg-secondary/30 p-3">
              <div className="min-w-0">
                <div className="font-label text-xs uppercase tracking-wider">
                  Self-custody
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Held in your own wallet (cold storage), not on an exchange.
                </div>
              </div>
              <Switch
                checked={isSelfCustody}
                onCheckedChange={(v) => setIsSelfCustody(Boolean(v))}
                aria-label="Self-custody"
              />
            </div>
          ) : null}

          {/* Notes */}
          <div>
            <Label htmlFor="ah-notes" className="eyebrow">
              Notes (optional)
            </Label>
            <Textarea
              id="ah-notes"
              placeholder="PPF account · maturity 2030 · SBI"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="mt-1 min-h-[60px]"
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!valid || addHolding.isPending}>
              {addHolding.isPending ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  Adding…
                </>
              ) : (
                <>
                  <Plus className="mr-2 h-3.5 w-3.5" />
                  Add holding
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
