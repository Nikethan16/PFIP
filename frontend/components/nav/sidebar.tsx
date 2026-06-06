"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { ChevronsUpDown, LogOut, Settings as SettingsIcon, UserCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { NetworkStatus } from "@/components/shared/network-status";
import { useUIStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { NAV_ITEMS, NAV_GROUP_LABELS, type NavGroup } from "./nav-items";

/**
 * Desktop sidebar — "Sahara" institutional terminal. Hidden on mobile; mobile
 * users get the bottom tab bar defined in `mobile-nav.tsx`.
 *
 * Layout
 *   ┌──────────────────┐
 *   │ ▰ PFIP  Terminal │  ← brand mark + serif wordmark, returns to /
 *   │ ● CORE ENGINE …  │  ← live engine-status line (backend reachability)
 *   ├──────────────────┤
 *   │ MARKETS          │
 *   │ │ DASHBOARD      │  ← Archivo Narrow caps; amber left-stripe when active
 *   │ │ WATCHLIST      │
 *   │ …                │
 *   ├──────────────────┤
 *   │ ● Online · IST   │  ← network status pill + clock
 *   │ user@host     ▾  │  ← profile menu (signed-in email + sign out)
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
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border/70 bg-[hsl(var(--sidebar))] text-[hsl(var(--sidebar-foreground))] md:flex">
      {/* Brand — serif wordmark over an "engine status" line, per Sahara shell. */}
      <div className="border-b border-border/60 px-4 py-4">
        <Link
          href={"/" as never}
          className="group flex items-center gap-2.5"
          aria-label="PFIP — go to dashboard"
        >
          <BrandMark />
          <div className="flex min-w-0 flex-col leading-none">
            <span className="font-serif text-lg tracking-tight text-foreground transition-colors group-hover:text-primary">
              PFIP
            </span>
            <span className="eyebrow mt-1 !text-[9px]">Terminal</span>
          </div>
        </Link>
        <EngineStatus />
      </div>

      {/* Primary action — advisory-only; opens the agent rather than trading. */}
      <div className="px-3 pt-3">
        <Link
          href={"/chat" as never}
          className="flex w-full items-center justify-center gap-2 bg-primary px-3 py-2.5 font-label text-[11px] uppercase tracking-[0.12em] text-primary-foreground transition-all hover:brightness-110"
        >
          Ask the analyst
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-3">
        {(Object.keys(itemsByGroup) as NavGroup[]).map((g, idx) => {
          const items = itemsByGroup[g];
          if (!items.length) return null;
          return (
            <div key={g} className={cn(idx > 0 && "mt-5")}>
              <div className="px-1 pb-1.5 eyebrow !text-[9px]">
                {NAV_GROUP_LABELS[g]}
              </div>
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
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "group relative flex items-center gap-2.5 border-l-2 py-1.5 pl-3 pr-2 font-label text-[12px] uppercase tracking-[0.08em] transition-colors",
                          active
                            ? "border-l-primary bg-accent/50 text-primary"
                            : "border-l-transparent text-muted-foreground hover:bg-accent/40 hover:text-foreground",
                        )}
                      >
                        <Icon
                          className={cn(
                            "h-[15px] w-[15px] shrink-0 transition-colors",
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

      {/* Footer: network pill + clock + user menu */}
      <div className="space-y-2 border-t border-border/60 p-3">
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
    <div className="relative flex h-9 w-9 items-center justify-center overflow-hidden border border-primary/30 bg-primary text-primary-foreground">
      <span className="relative z-10 font-serif text-sm leading-none tracking-tight">
        PF
      </span>
      <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.3),transparent_60%)]" />
    </div>
  );
}

/**
 * Live "engine status" line — green pulsing dot + "CORE ENGINE · ONLINE" when
 * the backend health ping is up, amber + "DEGRADED" when it isn't. The state is
 * the real `backendOnline` flag the NetworkStatus poller maintains.
 */
function EngineStatus() {
  const online = useUIStore((s) => s.backendOnline);
  return (
    <div className="mt-3 flex items-center gap-2">
      <span
        className={cn(
          "pfip-live-dot h-1.5 w-1.5 rounded-full",
          online ? "bg-emerald-500" : "bg-amber-500",
        )}
        aria-hidden
      />
      <span className="font-label text-[9px] uppercase tracking-[0.16em] text-muted-foreground">
        Core Engine · {online ? "Online" : "Degraded"}
      </span>
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
    <span className="select-none font-mono text-[11px] text-muted-foreground" title="Asia/Kolkata">
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
        className="flex w-full items-center gap-2 border border-border/70 bg-card px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent/40"
      >
        <UserCircle2 className="h-4 w-4 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-mono text-[11px]">{email}</span>
        <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="User menu"
          className="absolute bottom-[calc(100%+6px)] left-0 right-0 z-30 border border-border/70 bg-popover p-1 shadow-md"
        >
          <Link
            href={"/settings" as never}
            role="menuitem"
            className="flex items-center gap-2 px-2 py-1.5 font-label text-[11px] uppercase tracking-wider transition-colors hover:bg-accent/50"
            onClick={() => setOpen(false)}
          >
            <SettingsIcon className="h-3.5 w-3.5" />
            Settings
          </Link>
          <Button
            variant="ghost"
            size="sm"
            role="menuitem"
            className="h-7 w-full justify-start gap-2 px-2 font-label text-[11px] uppercase tracking-wider"
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
