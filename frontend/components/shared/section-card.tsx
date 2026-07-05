"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface SectionCardProps {
  /** Small uppercase eyebrow label at the top of the card. */
  title?: React.ReactNode;
  /** Optional right-aligned slot in the header row (badges, filters, links). */
  actions?: React.ReactNode;
  /** Sub-line under the title. */
  description?: React.ReactNode;
  className?: string;
  /** Remove the default padding (for tables/charts that manage their own). */
  flush?: boolean;
  children: React.ReactNode;
}

/**
 * The one canonical content card for the "Sahara" design system — a thin warm
 * border on a card surface, with a standard eyebrow header. Every page uses
 * this instead of ad-hoc ``border border-border/60 bg-card p-5`` blocks, so
 * spacing, borders, and header treatment are identical everywhere.
 */
export function SectionCard({
  title,
  actions,
  description,
  className,
  flush,
  children,
}: SectionCardProps) {
  return (
    <section className={cn("border border-border/60 bg-card", flush ? "" : "p-5", className)}>
      {title || actions ? (
        <div
          className={cn(
            "flex items-center justify-between gap-3",
            flush ? "border-b border-border/60 px-5 py-3" : "mb-3",
          )}
        >
          <div className="min-w-0">
            {title ? (
              <div className="font-label text-[10px] uppercase tracking-wider text-primary/80">
                {title}
              </div>
            ) : null}
            {description ? (
              <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
