import {
  BarChart3,
  BookOpen,
  Briefcase,
  Calculator,
  Cog,
  Eye,
  Home,
  MessageSquare,
  SlidersHorizontal,
  Stars,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  mobile?: boolean; // show in bottom tab bar
}

/** Keep this list the single source of truth for sidebar + mobile bar. */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", icon: Home, mobile: true },
  { label: "Portfolio", href: "/portfolio", icon: Briefcase, mobile: true },
  { label: "Chat", href: "/chat", icon: MessageSquare, mobile: true },
  { label: "Tax", href: "/tax", icon: Calculator, mobile: true },
  { label: "Journal", href: "/journal", icon: BookOpen, mobile: true },
  { label: "Signals", href: "/signals", icon: Stars },
  { label: "Watchlist", href: "/watchlist", icon: Eye },
  { label: "Calibration", href: "/calibration", icon: BarChart3 },
  { label: "Settings", href: "/settings", icon: Cog },
];

export const SECONDARY_NAV_ICON: LucideIcon = SlidersHorizontal;
