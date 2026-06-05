"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, ChevronRight, MessageSquare, Moon, Search, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import { NetworkStatus } from "@/components/shared/network-status";
import { useAuthToken } from "@/lib/api";
import { useUIStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { NAV_BY_PATH } from "./nav-items";

/**
 * Top bar. Visible on every page.
 *   - Left:   breadcrumb trail (mobile shows current page only).
 *   - Center: Cmd+K command palette trigger (search-or-jump).
 *   - Right:  network status pill, notifications bell, theme toggle, chat shortcut.
 *
 * The top bar is sticky and has a backdrop blur so it floats over scrolling
 * content without losing legibility.
 */
export function TopBar() {
  const setCommandOpen = useUIStore((s) => s.setCommandOpen);
  const { setTheme, resolvedTheme } = useTheme();
  const pathname = usePathname() ?? "/";

  const crumbs = React.useMemo(() => buildCrumbs(pathname), [pathname]);
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  return (
    <header className="sticky top-0 z-30 flex h-12 items-center justify-between gap-2 border-b bg-[hsl(var(--header))]/85 px-3 backdrop-blur sm:px-6">
      {/* Mobile brand */}
      <div className="flex items-center gap-2 md:hidden">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-gradient-to-br from-primary to-primary/60 text-primary-foreground shadow-sm">
          <span className="text-xs font-bold">PF</span>
        </div>
        <Breadcrumbs crumbs={crumbs} compact />
      </div>

      {/* Desktop breadcrumbs */}
      <div className="hidden flex-1 items-center md:flex">
        <Breadcrumbs crumbs={crumbs} />
      </div>

      {/* Command palette trigger */}
      <button
        type="button"
        onClick={() => setCommandOpen(true)}
        className="hidden h-8 w-72 items-center gap-2 rounded-md border bg-background/60 px-3 text-xs text-muted-foreground transition-colors hover:bg-accent md:flex"
        aria-label="Open command palette"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="flex-1 text-left">Search or jump to&hellip;</span>
        <kbd className="rounded border bg-muted px-1 text-[10px] text-muted-foreground">
          {mounted && typeof navigator !== "undefined" && navigator.platform.toLowerCase().includes("mac")
            ? "⌘"
            : "Ctrl"}
          K
        </kbd>
      </button>

      <div className="flex items-center gap-1.5">
        <div className="hidden md:block">
          <NetworkStatus />
        </div>
        <NotificationBell />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          aria-label="Toggle theme"
          title="Toggle theme"
          suppressHydrationWarning
        >
          {mounted ? (
            resolvedTheme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )
          ) : (
            <Moon className="h-4 w-4 opacity-0" />
          )}
        </Button>
        <Link
          href={"/chat" as never}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent md:hidden"
          aria-label="Open chat"
        >
          <MessageSquare className="h-4 w-4" />
        </Link>
        {/* Mobile command palette trigger */}
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent md:hidden"
          aria-label="Open command palette"
        >
          <Search className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

interface Crumb {
  label: string;
  href?: string;
}

function buildCrumbs(pathname: string): Crumb[] {
  // Build a list from the path; first crumb is always "PFIP" for context.
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) {
    return [{ label: "Dashboard" }];
  }
  const crumbs: Crumb[] = [{ label: "PFIP", href: "/" }];
  let accum = "";
  segments.forEach((seg, idx) => {
    accum += `/${seg}`;
    const nav = NAV_BY_PATH[accum];
    crumbs.push({
      label: nav?.label ?? toTitle(seg),
      href: idx === segments.length - 1 ? undefined : accum,
    });
  });
  return crumbs;
}

function toTitle(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Breadcrumbs({ crumbs, compact }: { crumbs: Crumb[]; compact?: boolean }) {
  if (compact) {
    const tail = crumbs[crumbs.length - 1];
    return (
      <span className="truncate text-sm font-medium">{tail?.label ?? "PFIP"}</span>
    );
  }
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-sm">
      {crumbs.map((c, i) => {
        const last = i === crumbs.length - 1;
        return (
          <React.Fragment key={`${c.label}-${i}`}>
            {c.href && !last ? (
              <Link
                href={c.href as never}
                className="truncate text-muted-foreground transition-colors hover:text-foreground"
              >
                {c.label}
              </Link>
            ) : (
              <span
                className={cn(
                  "truncate",
                  last ? "font-medium text-foreground" : "text-muted-foreground",
                )}
              >
                {c.label}
              </span>
            )}
            {!last ? (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            ) : null}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

/**
 * Notifications bell. Tries to fetch from the backend mirror endpoint
 * `/notifications/recent`; gracefully degrades to a static "no notifications"
 * state if the endpoint isn't available.
 */
function NotificationBell() {
  const [open, setOpen] = React.useState(false);
  const [count, setCount] = React.useState(0);
  const ref = React.useRef<HTMLDivElement | null>(null);
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);

  React.useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    if (open) {
      document.addEventListener("mousedown", onClick);
      document.addEventListener("keydown", onKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Best-effort poll. The endpoint may not exist yet; we silently fail.
  // Only runs when authenticated, and sends the backend bearer token — without
  // it every poll 401'd forever (and fired on the login page too).
  const token = useAuthToken();
  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;
    const base =
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
    const url = base.replace(/\/+$/, "").endsWith("/api/v1")
      ? `${base.replace(/\/+$/, "")}/notifications/recent`
      : `${base.replace(/\/+$/, "")}/api/v1/notifications/recent`;
    const tick = async () => {
      try {
        const resp = await fetch(url, {
          headers: {
            Accept: "application/json",
            Authorization: `Bearer ${token}`,
          },
        });
        if (!resp.ok) return;
        const data = (await resp.json()) as { unread?: number };
        if (!cancelled && typeof data.unread === "number") setCount(data.unread);
      } catch {
        // ignore — endpoint optional.
      }
    };
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [token]);

  return (
    <div ref={ref} className="relative">
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="icon"
        className="relative h-8 w-8"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Notifications${count ? ` (${count} unread)` : ""}`}
      >
        <Bell className="h-4 w-4" />
        {count > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-medium text-destructive-foreground">
            {count > 9 ? "9+" : count}
          </span>
        ) : null}
      </Button>
      {open ? (
        <div
          className="absolute right-0 top-[calc(100%+6px)] z-40 w-80 rounded-md border bg-popover p-3 text-popover-foreground shadow-xl"
          role="dialog"
        >
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-medium">Notifications</div>
            <span className="text-[10px] text-muted-foreground">
              {count} unread
            </span>
          </div>
          {count === 0 ? (
            <div className="rounded border border-dashed p-4 text-center text-xs text-muted-foreground">
              You&apos;re all caught up. Critical alerts from Telegram will mirror
              here when the backend wires the endpoint.
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">
              {count} new alert{count === 1 ? "" : "s"} — see Telegram or
              <Link href={"/settings" as never} className="ml-1 text-primary hover:underline">
                Settings
              </Link>
              .
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
