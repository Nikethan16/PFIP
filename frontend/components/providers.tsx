"use client";

import * as React from "react";
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { SessionProvider, useSession } from "next-auth/react";
import { ThemeProvider } from "next-themes";
import { Loader2 } from "lucide-react";

import { Toaster, toast } from "@/components/ui/toast";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { CommandPalette } from "@/components/shared/command-palette";
import { ApiError } from "@/lib/api";

/**
 * Root client-side providers. Wraps the whole app in:
 *   - NextAuth SessionProvider (for `useSession`)
 *   - TanStack Query with global cache hooks that surface toasts on errors
 *   - next-themes (light/dark toggle, defaults to system)
 *   - Sonner toaster (for mutation feedback)
 *   - ErrorBoundary (catches render-time errors below providers)
 *   - CommandPalette (Cmd+K) — always mounted so shortcut works on every page
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Short auto-retry so transient failures don't flash errors.
            retry: (failureCount, err) => {
              if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
                return false;
              }
              return failureCount < 2;
            },
            refetchOnWindowFocus: false,
            staleTime: 30_000,
          },
          mutations: {
            retry: 0,
          },
        },
        queryCache: new QueryCache({
          onError: (err) => {
            // Only toast non-auth errors; 401 is handled by apiFetch itself.
            if (err instanceof ApiError && err.status === 401) return;
            // eslint-disable-next-line no-console
            console.warn("[query error]", err);
          },
        }),
        mutationCache: new MutationCache({
          onError: (err) => {
            if (err instanceof ApiError && err.status === 401) return;
            toast.error((err as Error).message || "Request failed");
          },
        }),
      }),
  );

  return (
    <SessionProvider>
      <QueryClientProvider client={client}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <SessionGate>
            <ErrorBoundary>{children}</ErrorBoundary>
            <CommandPalette />
          </SessionGate>
          <Toaster position="top-right" richColors />
        </ThemeProvider>
      </QueryClientProvider>
    </SessionProvider>
  );
}

/**
 * Holds rendering of the app's data surfaces until NextAuth has hydrated the
 * session. Without this, the ~25 `useQuery` hooks below mount while
 * `useSession()` is still "loading" — so `useAuthToken()` returns null, those
 * requests go out with NO bearer token, the backend 401s them, and `apiFetch`
 * turns the first 401 into a forced sign-out (bouncing the user to /login with
 * half the data missing). The session resolves in a few hundred ms; a brief
 * loader here removes the race entirely. (`status` is only "loading" on a cold
 * load, not on client-side navigations, so there's no per-route flicker.)
 */
function SessionGate({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  if (status === "loading") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }
  return <>{children}</>;
}
