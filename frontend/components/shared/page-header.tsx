"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: React.ReactNode;
  /** Right-side content — e.g. action buttons, stale badge, filters. */
  actions?: React.ReactNode;
  className?: string;
  /** When true, removes the sticky background so the header scrolls with content. */
  flat?: boolean;
}

/**
 * Standardised page header used on every top-level route.
 *
 *   Title              <actions...>
 *   Description
 *
 * Sticks just below the topbar with a backdrop blur, so the title stays
 * anchored as the user scrolls deep tables/charts.
 */
export function PageHeader({
  title,
  description,
  actions,
  className,
  flat,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        flat
          ? "mb-4 flex flex-wrap items-start justify-between gap-3"
          : "page-header flex flex-wrap items-start justify-between gap-3",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          {title}
        </h1>
        {description ? (
          <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
