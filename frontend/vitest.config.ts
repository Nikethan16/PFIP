import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

/**
 * Vitest configuration for the PFIP frontend.
 *
 * - `jsdom` gives DOM globals (localStorage, window, etc.) so React/DOM bits
 *   and `sse.ts`-style helpers can be exercised. Pure-logic tests run fine
 *   under it too.
 * - The `@/` alias mirrors tsconfig.json `paths` (`"@/*": ["./*"]`) so test
 *   imports match application import style.
 * - `setupFiles` wires in `@testing-library/jest-dom` matchers.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}", "**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "dist"],
  },
});
