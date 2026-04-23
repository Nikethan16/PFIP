"use client";

import * as React from "react";
import { Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";

const STARTERS = [
  "Why is BTC up today?",
  "What's my exposure to IT sector?",
  "Which holdings are near stop-loss?",
  "Summarize this week's papers.",
];

interface SuggestedStartersProps {
  onPick: (text: string) => void;
  className?: string;
}

/** Tiny strip of prompt suggestions shown when the chat history is empty. */
export function SuggestedStarters({ onPick, className }: SuggestedStartersProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <Sparkles className="h-3 w-3" />
        Try asking
      </div>
      <div className="flex flex-wrap gap-2">
        {STARTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className={cn(
              "rounded-full border bg-background px-3 py-1.5 text-xs transition-colors",
              "hover:bg-accent hover:text-accent-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
