"use client";

import * as React from "react";
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { SessionProvider } from "next-auth/react";
import { ThemeProvider } from "next-themes";

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
          <ErrorBoundary>{children}</ErrorBoundary>
          <CommandPalette />
          <Toaster position="top-right" richColors />
        </ThemeProvider>
      </QueryClientProvider>
    </SessionProvider>
  );
}
