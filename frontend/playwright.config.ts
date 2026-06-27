import { defineConfig, devices } from "@playwright/test";

/**
 * PFIP end-to-end smoke + interaction suite.
 *
 * Drives a real Chromium browser against the LIVE deployment (the Oracle VM
 * behind Tailscale Funnel) by default: logs in once, sweeps every page, and
 * runs a few interaction flows — flagging broken pages, failed API calls,
 * console/schema errors, and "data not loading".
 *
 * Run (from frontend/):
 *   pnpm test:e2e            # headless, against the live VM
 *   pnpm test:e2e:headed     # watch it drive the browser
 *   pnpm test:e2e:ui         # Playwright's interactive runner
 *   pnpm test:e2e:report     # open the last HTML report
 *
 * Credentials come from env (never hard-coded). Put them in e2e/.env.local
 * (gitignored) or export them:
 *   PFIP_E2E_EMAIL, PFIP_E2E_PASSWORD   (required)
 *   PFIP_E2E_BASE_URL                   (optional; defaults to the live VM)
 */

// Minimal .env loader (no dotenv dependency): load e2e/.env.local if present so
// creds don't have to be exported each run. KEY=VALUE lines, # comments ignored.
import * as fs from "node:fs";
try {
  for (const line of fs.readFileSync("e2e/.env.local", "utf-8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && m[1] && !process.env[m[1]]) {
      process.env[m[1]] = (m[2] ?? "").replace(/^["']|["']$/g, "");
    }
  }
} catch {
  /* no e2e/.env.local — rely on exported env vars */
}

const BASE_URL =
  process.env.PFIP_E2E_BASE_URL ?? "https://apps.tail1d9a60.ts.net:8443";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.artifacts",
  // Generous: the live VM is a small ARM box and the chat flow hits an LLM.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // Don't hammer the single VM; a little parallelism is fine.
  fullyParallel: false,
  workers: process.env.CI ? 1 : 3,
  // One retry absorbs transient Funnel/network blips without hiding real breakage.
  retries: 1,
  forbidOnly: !!process.env.CI,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "e2e/report/html" }],
    ["./e2e/issue-reporter.ts"],
  ],
  use: {
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
    actionTimeout: 15_000,
    navigationTimeout: 45_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [
    // Logs in once and saves the session; every other project reuses it.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/user.json",
      },
      dependencies: ["setup"],
    },
  ],
});
