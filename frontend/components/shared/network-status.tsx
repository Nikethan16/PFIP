"use client";

import * as React from "react";
import { Wifi, WifiOff } from "lucide-react";

import { cn } from "@/lib/utils";
import { pingBackend } from "@/lib/api";
import { useUIStore } from "@/lib/store";

/**
 * Polls `/api/v1/health` every 30 s and reports a small indicator in the
 * corner of the app. Tooltip shows backend URL for debugging.
 */
export function NetworkStatus({ className }: { className?: string }) {
  const online = useUIStore((s) => s.backendOnline);
  const setOnline = useUIStore((s) => s.setBackendOnline);

  React.useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const ok = await pingBackend();
      if (!cancelled) setOnline(ok);
    };
    run();
    const id = window.setInterval(run, 30_000);
    const onOnline = () => run();
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", () => setOnline(false));
    return () => {
      cancelled = true;
      window.clearInterval(id);
      window.removeEventListener("online", onOnline);
    };
  }, [setOnline]);

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium",
        online
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
          : "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400",
        className,
      )}
      aria-live="polite"
      title={
        online ? "Backend reachable" : "Backend unreachable — data may be stale"
      }
    >
      {online ? (
        <Wifi className="h-3 w-3" />
      ) : (
        <WifiOff className="h-3 w-3" />
      )}
      <span>{online ? "Online" : "Offline"}</span>
    </div>
  );
}
