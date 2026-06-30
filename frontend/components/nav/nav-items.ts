import {
  Activity,
  BarChart3,
  BookOpen,
  Briefcase,
  Calculator,
  Cog,
  Copy,
  Eye,
  FlaskConical,
  GitCompareArrows,
  Heart,
  Home,
  LayoutDashboard,
  Lightbulb,
  LineChart,
  MessageSquare,
  Microscope,
  Newspaper,
  PiggyBank,
  ScanSearch,
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

export type NavGroup =
  | "overview"
  | "markets"
  | "trading"
  | "tax"
  | "tools"
  | "ops"
  | "system";

export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  overview: "Overview",
  markets: "Markets",
  trading: "Portfolio",
  tax: "Tax (India)",
  tools: "Tools",
  ops: "Operations",
  system: "Settings",
};

/** Single source of truth for sidebar + mobile bar + command palette.
 *
 * Eight top-level groups matching the Stitch ("PFIP Terminal · Institutional
 * Grade") shell. Each group expands into one or more pages.
 */
export const NAV_ITEMS: NavItem[] = [
  // Overview
  { label: "Dashboard", href: "/", icon: LayoutDashboard, mobile: true, group: "overview", shortcut: "G then D" },

  // Markets
  { label: "Watchlist", href: "/watchlist", icon: Eye, group: "markets", shortcut: "G then W" },
  { label: "Signals", href: "/signals", icon: Stars, group: "markets", shortcut: "G then S" },
  { label: "Events", href: "/events", icon: Newspaper, group: "markets" },
  { label: "Themes", href: "/themes", icon: Lightbulb, group: "markets" },
  { label: "Research", href: "/diligence", icon: ScanSearch, group: "markets", shortcut: "G then R" },
  { label: "Deep Research", href: "/research", icon: Microscope, group: "markets" },

  // Portfolio
  { label: "Holdings", href: "/portfolio", icon: Briefcase, mobile: true, group: "trading", shortcut: "G then P" },
  { label: "Net worth", href: "/net-worth", icon: Wallet, group: "trading" },
  { label: "Benchmark", href: "/benchmark", icon: Trophy, group: "trading" },
  { label: "What-if", href: "/what-if", icon: GitCompareArrows, group: "trading" },
  { label: "Stress test", href: "/stress-test", icon: ShieldAlert, group: "trading" },
  { label: "Shadow", href: "/shadow", icon: Copy, group: "trading" },

  // Tax
  { label: "Tax", href: "/tax", icon: Calculator, mobile: true, group: "tax", shortcut: "G then T" },
  { label: "Loss harvesting", href: "/tax/harvest", icon: Calculator, group: "tax" },

  // Tools
  { label: "Goals", href: "/goals", icon: Target, group: "tools" },
  { label: "SIP", href: "/sip", icon: PiggyBank, group: "tools" },
  { label: "Journal", href: "/journal", icon: BookOpen, mobile: true, group: "tools", shortcut: "G then J" },
  { label: "Chat", href: "/chat", icon: MessageSquare, mobile: true, group: "tools", shortcut: "G then C" },
  { label: "Perspectives", href: "/perspectives", icon: Users, group: "tools" },
  { label: "Calibration", href: "/calibration", icon: LineChart, group: "tools" },
  { label: "Backtest", href: "/backtest", icon: FlaskConical, group: "tools" },

  // Operations
  { label: "Source health", href: "/ops/sources", icon: Heart, group: "ops" },
  { label: "Schedules", href: "/ops/schedules", icon: Activity, group: "ops" },
  { label: "Models", href: "/ops/models", icon: Wrench, group: "ops" },

  // Settings
  { label: "Settings", href: "/settings", icon: Cog, group: "system" },
];

/** Used in topbar to render breadcrumb labels. */
export const NAV_BY_PATH: Record<string, NavItem> = NAV_ITEMS.reduce(
  (acc, item) => {
    acc[item.href] = item;
    return acc;
  },
  {} as Record<string, NavItem>,
);
