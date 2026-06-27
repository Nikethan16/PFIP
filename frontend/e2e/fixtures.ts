import {
  test as base,
  expect,
  type Page,
  type TestInfo,
} from "@playwright/test";

/**
 * Shared test fixtures.
 *
 * The `issues` fixture attaches console / network / page-error listeners to the
 * browser page and exposes a live record of anything that went wrong. The whole
 * point of this suite is to surface "data not loading" — which on this app shows
 * up as (a) a 4xx/5xx from /api/v1, (b) the API client's `[apiFetch] schema
 * validation failed` console.error when the backend shape drifts, or (c) an
 * uncaught JS error. We capture all three.
 */

export interface PageIssues {
  /** console.error messages that aren't on the benign allowlist. */
  consoleErrors: string[];
  /** Uncaught exceptions in the page (React render crashes, etc.). */
  pageErrors: string[];
  /** Backend API calls that returned >= 400. */
  failedRequests: { url: string; status: number; method: string }[];
  /** The exact "page silently shows no/partial data" signal from apiFetch. */
  schemaFailures: string[];
}

// console.error substrings that are noise, not bugs. Anything NOT matched here
// that shows up as console.error becomes a finding. Extend as real noise appears.
const BENIGN_CONSOLE = [
  "Download the React DevTools",
  "[Fast Refresh]",
  "Hydration", // Next hydration warnings — track separately if you ever care
  "ResizeObserver loop", // benign browser noise from chart libs
];

function isBenign(text: string): boolean {
  return BENIGN_CONSOLE.some((p) => text.includes(p));
}

/** Attach listeners to a page and return the live, mutating issue record. */
export function watchPage(page: Page): PageIssues {
  const issues: PageIssues = {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    schemaFailures: [],
  };

  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    // The API client logs this exact string when a backend payload fails Zod
    // validation — i.e. the page renders with no/partial data even though the
    // HTTP call "succeeded". This is the highest-signal "data not loading" clue.
    if (text.includes("[apiFetch] schema validation failed")) {
      issues.schemaFailures.push(text);
      return;
    }
    if (!isBenign(text)) issues.consoleErrors.push(text);
  });

  page.on("pageerror", (err) => issues.pageErrors.push(err.message));

  page.on("response", (resp) => {
    const url = resp.url();
    const status = resp.status();
    if (status >= 400 && url.includes("/api/v1/")) {
      issues.failedRequests.push({
        url,
        status,
        method: resp.request().method(),
      });
    }
  });

  return issues;
}

/** Attach the collected issues to the test so the reporter can aggregate them. */
export async function recordIssues(
  testInfo: TestInfo,
  label: string,
  issues: PageIssues,
): Promise<void> {
  await testInfo.attach("issues", {
    body: JSON.stringify({ label, ...issues }, null, 2),
    contentType: "application/json",
  });
}

export const test = base.extend<{ issues: PageIssues }>({
  issues: async ({ page }, use) => {
    const issues = watchPage(page);
    await use(issues);
  },
});

export { expect };
