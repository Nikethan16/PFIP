"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { NAV_BY_PATH } from "./nav-items";

export interface SectionTab {
  href: string;
  /** Optional label override; defaults to the nav item's label. */
  label?: string;
}

/**
 * Secondary tab bar for a section (e.g. Portfolio, Research). Renders one tab
 * per route and highlights the active one using longest-prefix matching, so a
 * nested route (`/tax/harvest`) activates its own tab rather than the parent
 * (`/tax`). Labels default to the shared nav definition so they stay in sync.
 *
 * This gives the "tabs under a section" IA without moving any routes — each
 * page keeps its own URL and content; the bar just ties siblings together.
 */
export function SectionTabs({
  tabs,
  className,
  "aria-label": ariaLabel = "Section",
}: {
  tabs: SectionTab[];
  className?: string;
  "aria-label"?: string;
}) {
  const pathname = usePathname() ?? "";

  // Longest matching href wins so nested routes don't also light the parent.
  let activeHref: string | null = null;
  for (const t of tabs) {
    const matches = pathname === t.href || pathname.startsWith(t.href + "/");
    if (matches && (activeHref === null || t.href.length > activeHref.length)) {
      activeHref = t.href;
    }
  }

  return (
    <nav
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center gap-x-1 gap-y-0 border-b border-border/60",
        className,
      )}
    >
      {tabs.map((t) => {
        const item = NAV_BY_PATH[t.href];
        const label = t.label ?? item?.label ?? t.href;
        const Icon = item?.icon;
        const active = t.href === activeHref;
        return (
          <Link
            key={t.href}
            href={t.href as never}
            aria-current={active ? "page" : undefined}
            className={cn(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 font-label text-[12px] uppercase tracking-[0.08em] transition-colors",
              active
                ? "border-b-primary text-primary"
                : "border-b-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

/** Portfolio section — holdings, analytics, and tax (India). */
export const PORTFOLIO_TABS: SectionTab[] = [
  { href: "/portfolio", label: "Holdings" },
  { href: "/net-worth" },
  { href: "/benchmark" },
  { href: "/what-if" },
  { href: "/stress-test" },
  { href: "/shadow" },
  { href: "/tax" },
  { href: "/tax/harvest", label: "Harvest" },
];

/** Research section — the two research surfaces, unified. */
export const RESEARCH_TABS: SectionTab[] = [
  { href: "/diligence", label: "Company research" },
  { href: "/research", label: "Deep research" },
];
