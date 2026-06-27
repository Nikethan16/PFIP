import { test, expect, recordIssues } from "./fixtures";

/**
 * Smoke sweep: open every navigable page as the logged-in user and flag
 * anything broken — failed API calls, schema/data mismatches, JS crashes, or an
 * unexpected bounce back to /login. Each page is screenshotted into the report
 * so you can also eyeball "this looks empty / wrong" at a glance.
 *
 * Keep ROUTES in sync with app/**\/page.tsx.
 */
const ROUTES: { path: string; name: string }[] = [
  { path: "/", name: "dashboard" },
  { path: "/portfolio", name: "portfolio" },
  { path: "/net-worth", name: "net-worth" },
  { path: "/goals", name: "goals" },
  { path: "/signals", name: "signals" },
  { path: "/watchlist", name: "watchlist" },
  { path: "/benchmark", name: "benchmark" },
  { path: "/stress-test", name: "stress-test" },
  { path: "/what-if", name: "what-if" },
  { path: "/sip", name: "sip" },
  { path: "/tax", name: "tax" },
  { path: "/tax/harvest", name: "tax-harvest" },
  { path: "/diligence", name: "diligence" },
  { path: "/journal", name: "journal" },
  { path: "/calibration", name: "calibration" },
  { path: "/backtest", name: "backtest" },
  { path: "/shadow", name: "shadow" },
  { path: "/chat", name: "chat" },
  { path: "/settings", name: "settings" },
  { path: "/ops/models", name: "ops-models" },
  { path: "/ops/schedules", name: "ops-schedules" },
  { path: "/ops/sources", name: "ops-sources" },
];

test.describe("smoke: every page loads with real data", () => {
  for (const { path, name } of ROUTES) {
    test(`page ${path} (${name})`, async ({ page, issues }, testInfo) => {
      const resp = await page.goto(path, { waitUntil: "domcontentloaded" });

      // 1) The HTML document itself must be OK.
      expect(resp?.status() ?? 0, `HTTP status for ${path}`).toBeLessThan(400);

      // 2) Let client queries (TanStack Query) settle. networkidle can be flaky
      //    on polling pages, so it's best-effort + a fixed grace period.
      await page
        .waitForLoadState("networkidle", { timeout: 20_000 })
        .catch(() => {});
      await page.waitForTimeout(1500);

      // 3) Must not have been bounced to /login (session/token broke).
      expect(page.url(), `unexpected redirect to login from ${path}`).not.toContain(
        "/login",
      );

      // 4) Full-page screenshot into the report for eyeball review.
      await testInfo.attach(`screenshot-${name}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: "image/png",
      });

      // 5) Record everything for the aggregated FINDINGS.md.
      await recordIssues(testInfo, path, issues);

      // 6) Hard failures: broken API calls, data/schema mismatches, JS crashes.
      expect(issues.failedRequests, `failed API calls on ${path}`).toEqual([]);
      expect(
        issues.schemaFailures,
        `data/schema mismatches on ${path} (page shows no/partial data)`,
      ).toEqual([]);
      expect(issues.pageErrors, `uncaught JS errors on ${path}`).toEqual([]);

      // 7) Other console errors are reported but don't fail the sweep (noise
      //    varies); they show up in FINDINGS.md and the HTML report.
      if (issues.consoleErrors.length) {
        testInfo.annotations.push({
          type: "console-errors",
          description: issues.consoleErrors.join(" | "),
        });
      }
    });
  }
});
