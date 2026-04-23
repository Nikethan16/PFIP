"use client";

import Link from "next/link";
import { MessageSquare, Moon, Search, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import { NetworkStatus } from "@/components/shared/network-status";
import { useUIStore } from "@/lib/store";

/**
 * Top bar. Visible on every page.
 *   - Mobile: branding + chat shortcut + command button.
 *   - Desktop: Cmd+K hint, network status, theme toggle.
 */
export function TopBar() {
  const setCommandOpen = useUIStore((s) => s.setCommandOpen);
  const { theme, setTheme } = useTheme();

  return (
    <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b bg-background/95 px-4 backdrop-blur">
      <div className="flex items-center gap-2 md:hidden">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-primary text-primary-foreground">
          <span className="text-xs font-bold">PF</span>
        </div>
        <span className="text-sm font-semibold">PFIP</span>
      </div>

      {/* Desktop: command palette trigger, network, theme. */}
      <button
        type="button"
        onClick={() => setCommandOpen(true)}
        className="hidden h-8 flex-1 max-w-xs items-center gap-2 rounded-md border bg-background px-3 text-xs text-muted-foreground hover:bg-accent md:flex"
        aria-label="Open command palette"
      >
        <Search className="h-3.5 w-3.5" />
        <span>Search or jump to…</span>
        <kbd className="ml-auto rounded border bg-muted px-1 text-[10px] text-muted-foreground">
          ⌘K
        </kbd>
      </button>

      <div className="flex items-center gap-2">
        <div className="hidden md:block">
          <NetworkStatus />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label="Toggle theme"
          title="Toggle theme"
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>
        <Link
          href={"/chat" as never}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent md:hidden"
          aria-label="Open chat"
        >
          <MessageSquare className="h-4 w-4" />
        </Link>
      </div>
    </header>
  );
}
