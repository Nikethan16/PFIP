"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import {
  BookOpen,
  Briefcase,
  Calculator,
  Cog,
  Eye,
  Home,
  MessageSquare,
  Moon,
  PlusCircle,
  Search,
  Sparkles,
  Stars,
  Sun,
} from "lucide-react";
import { useTheme } from "next-themes";

import { useUIStore } from "@/lib/store";
import { cn } from "@/lib/utils";

/**
 * Cmd+K / Ctrl+K command palette.
 *
 * Keeps keyboard shortcuts visible inline. Quick actions:
 *   - Navigate to each major page
 *   - Toggle dark mode
 *   - Start a new journal entry
 *   - Open chat
 */
export function CommandPalette() {
  const open = useUIStore((s) => s.commandOpen);
  const setOpen = useUIStore((s) => s.setCommandOpen);
  const router = useRouter();
  const { theme, setTheme } = useTheme();

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href as never);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 p-4 pt-24"
      onClick={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <Command
        className="w-full max-w-lg overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-xl"
        loop
      >
        <div className="flex items-center border-b px-3">
          <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          <Command.Input
            placeholder="Type a command or search…"
            className="flex h-11 w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
            autoFocus
          />
        </div>
        <Command.List className="max-h-[60vh] overflow-y-auto p-2">
          <Command.Empty className="p-4 text-center text-sm text-muted-foreground">
            No results found.
          </Command.Empty>

          <Command.Group
            heading="Navigate"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-muted-foreground"
          >
            <PaletteItem icon={Home} label="Go to dashboard" onSelect={() => go("/")} />
            <PaletteItem icon={Briefcase} label="Go to portfolio" onSelect={() => go("/portfolio")} />
            <PaletteItem icon={MessageSquare} label="Open chat" onSelect={() => go("/chat")} />
            <PaletteItem icon={Calculator} label="Go to tax" onSelect={() => go("/tax")} />
            <PaletteItem icon={BookOpen} label="Open journal" onSelect={() => go("/journal")} />
            <PaletteItem icon={Stars} label="View signals" onSelect={() => go("/signals")} />
            <PaletteItem icon={Eye} label="View watchlist" onSelect={() => go("/watchlist")} />
            <PaletteItem icon={Sparkles} label="Calibration report" onSelect={() => go("/calibration")} />
            <PaletteItem icon={Cog} label="Open settings" onSelect={() => go("/settings")} />
          </Command.Group>

          <Command.Group
            heading="Actions"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-muted-foreground"
          >
            <PaletteItem
              icon={PlusCircle}
              label="New journal entry (pre-trade checklist)"
              onSelect={() => go("/journal?new=1")}
            />
            <PaletteItem
              icon={theme === "dark" ? Sun : Moon}
              label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              onSelect={() => {
                setTheme(theme === "dark" ? "light" : "dark");
                setOpen(false);
              }}
            />
          </Command.Group>
        </Command.List>
        <div className="flex items-center justify-between border-t px-3 py-2 text-[10px] text-muted-foreground">
          <span>
            <kbd className="rounded border px-1">↑↓</kbd> navigate{" "}
            <kbd className="rounded border px-1">↵</kbd> select
          </span>
          <span>
            <kbd className="rounded border px-1">Esc</kbd> close
          </span>
        </div>
      </Command>
    </div>
  );
}

function PaletteItem({
  icon: Icon,
  label,
  onSelect,
}: {
  icon: typeof Home;
  label: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm",
        "aria-selected:bg-accent aria-selected:text-accent-foreground",
      )}
    >
      <Icon className="h-4 w-4 text-muted-foreground" />
      {label}
    </Command.Item>
  );
}
