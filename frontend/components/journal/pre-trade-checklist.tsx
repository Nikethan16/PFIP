"use client";

import * as React from "react";
import { useForm, Controller } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PreTradeChecklistSchema, type PreTradeChecklist } from "@/lib/contracts";
import { useCreateJournalEntry } from "@/lib/api";
import { toast } from "@/components/ui/toast";

interface PreTradeChecklistDialogProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}

/**
 * 10-item pre-trade checklist (Appendix B of the PFIP plan).
 *
 * The 10 items enforced here:
 *   1. Thesis (free text, ≥ 10 chars)
 *   2. Invalidation (what makes this wrong)
 *   3. Position size (% of portfolio)
 *   4. Stop-loss % (optional — may be managed by drawdown halt instead)
 *   5. Time horizon
 *   6. Correlation check
 *   7. Liquidity check
 *   8. Tax impact considered
 *   9. News / catalysts checked
 *   10. Regime alignment + conviction score
 */
export function PreTradeChecklistDialog({
  open,
  onOpenChange,
}: PreTradeChecklistDialogProps) {
  const createEntry = useCreateJournalEntry();

  // We validate on submit using the Zod schema — no resolver needed.
  const form = useForm<{
    asset: string;
    direction: "BUY" | "HOLD" | "SELL";
    pre_trade: PreTradeChecklist;
  }>({
    defaultValues: {
      asset: "",
      direction: "BUY",
      pre_trade: {
        thesis: "",
        invalidation: "",
        position_size_pct: 5,
        stop_loss_pct: 10,
        time_horizon: "1-3 months",
        correlation_check: false,
        liquidity_check: false,
        tax_impact_considered: false,
        news_check: false,
        regime_alignment: false,
        conviction_score: 5,
      },
    },
  });

  const onSubmit = form.handleSubmit(async (vals) => {
    const parsed = PreTradeChecklistSchema.safeParse(vals.pre_trade);
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Checklist invalid");
      return;
    }
    if (!vals.asset.trim()) {
      toast.error("Enter an asset symbol");
      return;
    }
    try {
      await createEntry.mutateAsync({
        asset: vals.asset.trim(),
        direction: vals.direction,
        pre_trade: parsed.data,
      });
      toast.success("Journal entry created");
      onOpenChange(false);
      form.reset();
    } catch (err) {
      toast.error((err as Error).message);
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Pre-trade checklist</DialogTitle>
          <DialogDescription>
            All ten boxes must be answered before an entry is recorded. Based
            on PFIP plan Appendix B.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <Label htmlFor="asset">Asset</Label>
              <Input
                id="asset"
                placeholder="BTC-USD, RELIANCE.NS, SPY…"
                {...form.register("asset")}
              />
            </div>
            <div>
              <Label>Direction</Label>
              <Controller
                control={form.control}
                name="direction"
                render={({ field }) => (
                  <Select
                    value={field.value}
                    onValueChange={(v) =>
                      field.onChange(v as "BUY" | "HOLD" | "SELL")
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="BUY">BUY</SelectItem>
                      <SelectItem value="HOLD">HOLD</SelectItem>
                      <SelectItem value="SELL">SELL</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="thesis">1. Thesis</Label>
            <Textarea
              id="thesis"
              placeholder="Why this, why now?"
              rows={2}
              {...form.register("pre_trade.thesis")}
            />
          </div>

          <div>
            <Label htmlFor="invalidation">2. Invalidation</Label>
            <Textarea
              id="invalidation"
              placeholder="What observable fact would make this thesis wrong?"
              rows={2}
              {...form.register("pre_trade.invalidation")}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="size">3. Size (% of portfolio)</Label>
              <Input
                id="size"
                type="number"
                step="0.1"
                min={0}
                max={100}
                {...form.register("pre_trade.position_size_pct", {
                  valueAsNumber: true,
                })}
              />
            </div>
            <div>
              <Label htmlFor="stop">4. Stop loss %</Label>
              <Input
                id="stop"
                type="number"
                step="0.1"
                min={0}
                max={100}
                {...form.register("pre_trade.stop_loss_pct", {
                  valueAsNumber: true,
                })}
              />
            </div>
            <div>
              <Label htmlFor="horizon">5. Horizon</Label>
              <Input
                id="horizon"
                placeholder="1-3 months"
                {...form.register("pre_trade.time_horizon")}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(
              [
                ["correlation_check", "6. Correlation check vs existing book"],
                ["liquidity_check", "7. Liquidity check (exit plan)"],
                ["tax_impact_considered", "8. Tax impact considered"],
                ["news_check", "9. News / catalysts reviewed"],
                ["regime_alignment", "10a. Aligns with current regime"],
              ] as const
            ).map(([key, label]) => (
              <Controller
                key={key}
                control={form.control}
                name={`pre_trade.${key}` as const}
                render={({ field }) => (
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={(v) => field.onChange(Boolean(v))}
                    />
                    {label}
                  </label>
                )}
              />
            ))}
            <div>
              <Label htmlFor="conviction">10b. Conviction (1–10)</Label>
              <Input
                id="conviction"
                type="number"
                min={1}
                max={10}
                {...form.register("pre_trade.conviction_score", {
                  valueAsNumber: true,
                })}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createEntry.isPending}>
              {createEntry.isPending ? "Saving…" : "Save entry"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
