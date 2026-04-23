"use client";

import * as React from "react";
import { Controller, useForm } from "react-hook-form";

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
import { PostMortemSchema, type PostMortem } from "@/lib/contracts";
import { useCloseJournalEntry } from "@/lib/api";
import { toast } from "@/components/ui/toast";

interface PostMortemFormProps {
  open: boolean;
  entryId: string | null;
  onOpenChange: (next: boolean) => void;
}

/** Post-mortem fields follow PFIP plan Appendix C. */
export function PostMortemForm({
  open,
  entryId,
  onOpenChange,
}: PostMortemFormProps) {
  const closeEntry = useCloseJournalEntry();

  const form = useForm<PostMortem>({
    defaultValues: {
      outcome_pnl_inr: 0,
      outcome_pnl_pct: 0,
      thesis_correct: true,
      followed_plan: true,
      what_worked: "",
      what_didnt: "",
      lessons: "",
      next_actions: "",
    },
  });

  const onSubmit = form.handleSubmit(async (vals) => {
    const parsed = PostMortemSchema.safeParse(vals);
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Post-mortem invalid");
      return;
    }
    if (!entryId) return;
    try {
      await closeEntry.mutateAsync({ id: entryId, post_mortem: parsed.data });
      toast.success("Post-mortem saved");
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
          <DialogTitle>Post-mortem</DialogTitle>
          <DialogDescription>
            Close the loop on this trade. Honest answers compound.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="pnl_inr">P&amp;L (INR)</Label>
              <Input
                id="pnl_inr"
                type="number"
                step="0.01"
                {...form.register("outcome_pnl_inr", { valueAsNumber: true })}
              />
            </div>
            <div>
              <Label htmlFor="pnl_pct">P&amp;L (%)</Label>
              <Input
                id="pnl_pct"
                type="number"
                step="0.01"
                {...form.register("outcome_pnl_pct", { valueAsNumber: true })}
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-4">
            <Controller
              control={form.control}
              name="thesis_correct"
              render={({ field }) => (
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(v) => field.onChange(Boolean(v))}
                  />
                  Thesis correct
                </label>
              )}
            />
            <Controller
              control={form.control}
              name="followed_plan"
              render={({ field }) => (
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(v) => field.onChange(Boolean(v))}
                  />
                  Followed the plan
                </label>
              )}
            />
          </div>

          <div>
            <Label htmlFor="worked">What worked</Label>
            <Textarea id="worked" rows={2} {...form.register("what_worked")} />
          </div>
          <div>
            <Label htmlFor="didnt">What didn't work</Label>
            <Textarea id="didnt" rows={2} {...form.register("what_didnt")} />
          </div>
          <div>
            <Label htmlFor="lessons">Lessons</Label>
            <Textarea id="lessons" rows={2} {...form.register("lessons")} />
          </div>
          <div>
            <Label htmlFor="next_actions">Next actions</Label>
            <Textarea
              id="next_actions"
              rows={2}
              {...form.register("next_actions")}
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
            <Button type="submit" disabled={closeEntry.isPending}>
              {closeEntry.isPending ? "Saving…" : "Close trade"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
