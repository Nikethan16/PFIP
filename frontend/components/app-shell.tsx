"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

import { MobileNav } from "@/components/nav/mobile-nav";
import { Sidebar } from "@/components/nav/sidebar";
import { TopBar } from "@/components/nav/topbar";
import { ChatWidget } from "@/components/chat/chat-widget";

/**
 * Client boundary that decides whether to wrap children in the full app chrome
 * (sidebar + topbar + mobile nav + the global chat widget) or render them bare.
 *
 * Auth / standalone routes — currently `/login` and any future `/auth/*` — get a
 * clean, full-screen surface with no navigation and no chat FAB. Every other
 * route gets the cockpit chrome. The structure for the chrome branch is a
 * verbatim port of what `app/layout.tsx` used to render inline, so visual
 * output is unchanged for in-app pages.
 */
function isBareRoute(pathname: string | null): boolean {
  if (!pathname) return false;
  return pathname === "/login" || pathname.startsWith("/auth");
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (isBareRoute(pathname)) {
    return <main className="min-h-dvh">{children}</main>;
  }

  return (
    <div className="flex min-h-dvh w-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 pb-20 md:pb-0">
          <div className="mx-auto w-full max-w-[1400px] px-3 py-4 sm:px-6 lg:px-8">
            {children}
          </div>
        </main>
        <MobileNav />
      </div>
      <ChatWidget />
    </div>
  );
}
