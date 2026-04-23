"use client";

import * as React from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    href?: string;
    onClick?: () => void;
  };
  className?: string;
}

/**
 * Consistent empty-state surface. Always renders:
 *   - icon
 *   - title
 *   - description
 *   - CTA action (optional)
 *
 * Every list/table in PFIP should render this when there's no data, rather
 * than a bare "empty" message.
 */
export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-8 text-center",
        className,
      )}
      role="status"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="h-5 w-5" aria-hidden />
      </div>
      <div className="space-y-1">
        <div className="text-sm font-medium">{title}</div>
        {description ? (
          <div className="max-w-sm text-xs text-muted-foreground">
            {description}
          </div>
        ) : null}
      </div>
      {action ? (
        action.href ? (
          <Button asChild size="sm" variant="outline">
            <Link href={action.href as never}>{action.label}</Link>
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={action.onClick}>
            {action.label}
          </Button>
        )
      ) : null}
    </div>
  );
}
