import {
  Activity,
  BookOpen,
  Briefcase,
  Calculator,
  Cog,
  Copy,
  Eye,
  FlaskConical,
  GitCompareArrows,
  Heart,
  LayoutDashboard,
  LineChart,
  Lightbulb,
  MessageSquare,
  Microscope,
  Newspaper,
  PiggyBank,
  ScanSearch,
  Scissors,
  ShieldAlert,
  Stars,
  Target,
  Trophy,
  Users,
  Wallet,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  mobile?: boolean; // show in bottom tab bar
  group: NavGroup;
  shortcut?: string;
}

/**
 * Six top-level sections (was 25 flat items across 8 groups). The old menu
 * surfaced every page at once; this collapses them into task-oriented
 * sections so the daily surface stays small and the power-user tools live in
 * a collapsed "Lab". Routes are unchanged — only the grouping moved.
 */
export type NavGroup =
  | "home"
  | "research"
  | "portfolio"
  | "plan"
  | "lab"
  | "settings";

export interface NavGroupDef {
  id: NavGroup;
  label: string;
  /** Sections start expanded except Lab (power-user tools, kept out of the way). */
  defaultOpen: boolean;
}

/** Section order + default open/closed state for the sidebar. */
export const NAV_GROUPS: NavGroupDef[] = [
  { id: "home", label: "Home", defaultOpen: true },
  { id: "research", label: "Research", defaultOpen: true },
  { id: "portfolio", label: "Portfolio", defaultOpen: true },
  { id: "plan", label: "Plan", defaultOpen: true },
  { id: "lab", label: "Lab", defaultOpen: false },
  { id: "settings", label: "Settings", defaultOpen: true },
];

/** Back-compat label lookup (used anywhere that references a group by id). */
export const NAV_GROUP_LABELS: Record<NavGroup, string> = NAV_GROUPS.reduce(
  (acc, g) => {
    acc[g.id] = g.label;
    return acc;
  },
  {} as Record<NavGroup, string>,
);

/** Single source of truth for sidebar + mobile bar + breadcrumbs. */
export const NAV_ITEMS: NavItem[] = [
  // Home — daily landing + the assistant.
  { label: "Dashboard", href: "/", icon: LayoutDashboard, mobile: true, group: "home", shortcut: "G then D" },
  { label: "Chat", href: "/chat", icon: MessageSquare, mobile: true, group: "home", shortcut: "G then C" },

  // Research — understand names and the market.
  { label: "Research", href: "/diligence", icon: ScanSearch, mobile: true, group: "research", shortcut: "G then R" },
  { label: "Deep research", href: "/research", icon: Microscope, group: "research" },
  { label: "Events", href: "/events", icon: Newspaper, group: "research" },
  { label: "Themes", href: "/themes", icon: Lightbulb, group: "research" },

  // Portfolio — holdings, analytics, and tax (India).
  { label: "Holdings", href: "/portfolio", icon: Briefcase, mobile: true, group: "portfolio", shortcut: "G then P" },
  { label: "Net worth", href: "/net-worth", icon: Wallet, group: "portfolio" },
  { label: "Benchmark", href: "/benchmark", icon: Trophy, group: "portfolio" },
  { label: "What-if", href: "/what-if", icon: GitCompareArrows, group: "portfolio" },
  { label: "Stress test", href: "/stress-test", icon: ShieldAlert, group: "portfolio" },
  { label: "Shadow", href: "/shadow", icon: Copy, group: "portfolio" },
  { label: "Tax", href: "/tax", icon: Calculator, group: "portfolio", shortcut: "G then T" },
  { label: "Loss harvesting", href: "/tax/harvest", icon: Scissors, group: "portfolio" },

  // Plan — goals, SIPs, watchlist, and the decision journal.
  { label: "Goals", href: "/goals", icon: Target, group: "plan" },
  { label: "SIP", href: "/sip", icon: PiggyBank, group: "plan" },
  { label: "Watchlist", href: "/watchlist", icon: Eye, group: "plan", shortcut: "G then W" },
  { label: "Journal", href: "/journal", icon: BookOpen, mobile: true, group: "plan", shortcut: "G then J" },

  // Lab — signals R&D + operations. Collapsed by default; experimental.
  { label: "Signals", href: "/signals", icon: Stars, group: "lab", shortcut: "G then S" },
  { label: "Calibration", href: "/calibration", icon: LineChart, group: "lab" },
  { label: "Backtest", href: "/backtest", icon: FlaskConical, group: "lab" },
  { label: "Perspectives", href: "/perspectives", icon: Users, group: "lab" },
  { label: "Source health", href: "/ops/sources", icon: Heart, group: "lab" },
  { label: "Schedules", href: "/ops/schedules", icon: Activity, group: "lab" },
  { label: "Models", href: "/ops/models", icon: Wrench, group: "lab" },

  // Settings
  { label: "Settings", href: "/settings", icon: Cog, group: "settings" },
];

/** Used in topbar to render breadcrumb labels. */
export const NAV_BY_PATH: Record<string, NavItem> = NAV_ITEMS.reduce(
  (acc, item) => {
    acc[item.href] = item;
    return acc;
  },
  {} as Record<string, NavItem>,
);
