"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { ChevronsUpDown, LogOut, Settings as SettingsIcon, UserCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { NetworkStatus } from "@/components/shared/network-status";
import { cn } from "@/lib/utils";
import { NAV_ITEMS, NAV_GROUP_LABELS, type NavGroup } from "./nav-items";

/**
 * Desktop sidebar. Hidden on mobile; mobile users get the bottom tab bar
 * defined in `mobile-nav.tsx`.
 *
 * Layout
 *   ┌──────────────────┐
 *   │ PFIP brand mark  │  ← clickable, returns to /
 *   ├──────────────────┤
 *   │ Markets          │
 *   │ • Dashboard      │
 *   │ • Watchlist      │
 *   │ • Signals        │
 *   │                  │
 *   │ Trading          │
 *   │ • Portfolio …    │
 *   ├──────────────────┤
 *   │ • Online · IST   │  ← network status pill + clock
 *   │ • user@host  ▾   │  ← profile menu (signed-in email + sign out)
 *   └──────────────────┘
 */
export function Sidebar() {
  const pathname = usePathname();
  const { data: session } = useSession();

  const itemsByGroup = React.useMemo(() => {
    const map: Record<NavGroup, typeof NAV_ITEMS> = {
      overview: [],
      markets: [],
      trading: [],
      tax: [],
      tools: [],
      ops: [],
      system: [],
    };
    NAV_ITEMS.forEach((i) => map[i.group].push(i));
    return map;
  }, []);

  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r bg-[hsl(var(--sidebar))] text-[hsl(var(--sidebar-foreground))] md:flex">
      {/* Brand — "PFIP Terminal · Institutional Grade" per Stitch design. */}
      <Link
        href={"/" as never}
        className="flex h-14 items-center gap-2.5 border-b border-[hsl(var(--sidebar-border))] px-4 transition-colors hover:bg-accent/30"
      >
        <BrandMark />
        <div className="flex min-w-0 flex-col">
          <span className="text-sm font-semibold tracking-tight text-primary">
            PFIP Terminal
          </span>
          <span className="truncate text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Institutional Grade
          </span>
        </div>
      </Link>

      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {(Object.keys(itemsByGroup) as NavGroup[]).map((g, idx) => {
          const items = itemsByGroup[g];
          if (!items.length) return null;
          return (
            <div key={g} className={cn(idx > 0 && "mt-4")}>
              <div className="px-2 pb-1 eyebrow">{NAV_GROUP_LABELS[g]}</div>
              <ul className="space-y-px">
                {items.map((item) => {
                  const active =
                    item.href === "/"
                      ? pathname === "/"
                      : pathname?.startsWith(item.href);
                  const Icon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href as never}
                        className={cn(
                          "group relative flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium transition-all",
                          active
                            ? "bg-accent text-accent-foreground"
                            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                        )}
                      >
                        {active ? (
                          <span
                            className="absolute inset-y-1.5 left-0 w-0.5 rounded-r bg-primary"
                            aria-hidden
                          />
                        ) : null}
                        <Icon
                          className={cn(
                            "h-[15px] w-[15px] transition-colors",
                            active
                              ? "text-primary"
                              : "text-muted-foreground group-hover:text-foreground",
                          )}
                        />
                        <span className="flex-1 truncate">{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      {/* Footer: network pill + user menu */}
      <div className="space-y-2 border-t border-[hsl(var(--sidebar-border))] p-3">
        <div className="flex items-center justify-between gap-2">
          <NetworkStatus />
          <Clock />
        </div>
        <UserMenu email={session?.user?.email ?? "Signed out"} onSignOut={() => signOut({ callbackUrl: "/login" })} />
      </div>
    </aside>
  );
}

function BrandMark() {
  return (
    <div className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-md bg-gradient-to-br from-primary to-primary/60 text-primary-foreground shadow-sm">
      <span className="relative z-10 text-xs font-bold tracking-tight">PF</span>
      <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.35),transparent_60%)]" />
    </div>
  );
}

function Clock() {
  const [time, setTime] = React.useState<string>("");
  React.useEffect(() => {
    const tick = () => {
      const now = new Date();
      const ist = new Intl.DateTimeFormat("en-IN", {
        timeZone: "Asia/Kolkata",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(now);
      setTime(`${ist} IST`);
    };
    tick();
    const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="select-none font-num text-[11px] text-muted-foreground" title="Asia/Kolkata">
      {time}
    </span>
  );
}

function UserMenu({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);

  // Close on outside click (works for keyboard-driven focus moves too, which
  // dispatch pointer events) and on Escape, returning focus to the trigger.
  React.useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex w-full items-center gap-2 rounded-md border bg-background px-2 py-1.5 text-left text-xs hover:bg-accent"
      >
        <UserCircle2 className="h-4 w-4 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">{email}</span>
        <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="User menu"
          className="absolute bottom-[calc(100%+6px)] left-0 right-0 z-30 rounded-md border bg-popover p-1 shadow-md"
        >
          <Link
            href={"/settings" as never}
            role="menuitem"
            className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-accent"
            onClick={() => setOpen(false)}
          >
            <SettingsIcon className="h-3.5 w-3.5" />
            Settings
          </Link>
          <Button
            variant="ghost"
            size="sm"
            role="menuitem"
            className="h-7 w-full justify-start gap-2 px-2 text-xs"
            onClick={onSignOut}
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </Button>
        </div>
      ) : null}
    </div>
  );
}
