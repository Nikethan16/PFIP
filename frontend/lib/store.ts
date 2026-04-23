"use client";

/**
 * Lightweight client-side store (zustand). Used for ephemeral UI state that
 * doesn't belong in TanStack Query's server cache:
 *   - network connectivity indicator
 *   - command-palette open/closed
 *   - chat session persistence key
 *
 * Anything that touches the backend should still go through `lib/api.ts`.
 */

import { create } from "zustand";

interface UIState {
  /** True when the backend `/health` ping succeeded recently. */
  backendOnline: boolean;
  setBackendOnline: (next: boolean) => void;

  /** Command-palette (Cmd+K). */
  commandOpen: boolean;
  setCommandOpen: (next: boolean) => void;
  toggleCommand: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  backendOnline: true,
  setBackendOnline: (backendOnline) => set({ backendOnline }),

  commandOpen: false,
  setCommandOpen: (commandOpen) => set({ commandOpen }),
  toggleCommand: () => set((s) => ({ commandOpen: !s.commandOpen })),
}));
