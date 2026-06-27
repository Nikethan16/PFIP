import * as path from "node:path";
import { test, expect, recordIssues } from "./fixtures";

/**
 * Interaction flows — exercise the app the way a user actually would, beyond
 * just loading pages. All three are NON-DESTRUCTIVE on the live data:
 *   - goals: a Monte-Carlo projection (pure compute, no writes)
 *   - chat:  ask the agent one question (hits the live LLM; no writes)
 *   - portfolio import: a DRY-RUN CSV preview (dry_run=true → nothing persisted)
 *
 * Note: the chat flow makes a real (small) LLM call each run.
 */

test.describe("interactions: core user flows", () => {
  test("goals: run a Monte-Carlo projection", async ({ page, issues }, testInfo) => {
    await page.goto("/goals", { waitUntil: "domcontentloaded" });

    // The form ships with sensible defaults; just run it.
    await page.getByRole("button", { name: /^project/i }).click();

    // A result KPI should appear, and no error banner.
    await expect(
      page.getByText("Median outcome"),
      "projection result did not render",
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Expected")).toBeVisible();

    await recordIssues(testInfo, "/goals [project]", issues);
    expect(issues.failedRequests, "failed API calls during goal projection").toEqual(
      [],
    );
    expect(issues.schemaFailures, "schema mismatch in projection response").toEqual(
      [],
    );
    expect(issues.pageErrors).toEqual([]);
  });

  test("chat: agent endpoint streams a response", async ({
    page,
    issues,
  }, testInfo) => {
    await page.goto("/chat", { waitUntil: "domcontentloaded" });

    const input = page.getByRole("textbox", { name: /chat input/i });
    await expect(input, "chat input not found").toBeVisible();

    // Assert the streaming round-trip is wired correctly: the POST to the agent
    // endpoint returns 200 text/event-stream — i.e. the auth token was attached,
    // the URL is right, and the server is streaming. We deliberately do NOT
    // assert full token accumulation: headless Chromium aborts a long-lived SSE
    // fetch through the Tailscale Funnel at the transport layer (no app code
    // involved). The backend streaming itself is verified out-of-band (curl).
    const log = page.getByRole("log");
    await input.fill("In one sentence, what is rupee cost averaging?");
    const [resp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/api/v1/agent/chat") && r.request().method() === "POST",
        { timeout: 30_000 },
      ),
      page.getByRole("button", { name: /^send$/i }).click(),
    ]);
    expect(resp.status(), "agent chat did not return 200").toBe(200);
    expect(
      resp.headers()["content-type"] ?? "",
      "agent chat response is not an SSE stream",
    ).toContain("text/event-stream");

    // The user's message should render in the transcript (proves send wired up).
    await expect(log, "user message did not appear in transcript").toContainText(
      "rupee cost averaging",
      { timeout: 15_000 },
    );

    await recordIssues(testInfo, "/chat [ask]", issues);
    expect(issues.pageErrors, "JS errors during chat").toEqual([]);
  });

  test("portfolio: dry-run a CSV import (no writes)", async ({
    page,
    issues,
  }, testInfo) => {
    await page.goto("/portfolio", { waitUntil: "domcontentloaded" });

    // Pin the broker so the parse is deterministic (auto-detect also works).
    await page
      .getByLabel("Broker")
      .selectOption("zerodha")
      .catch(() => {});

    // Selecting a file auto-fires the dry-run import (dry_run=true → no writes).
    const csv = path.join(__dirname, "fixtures", "zerodha_tradebook.csv");
    const [importResp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/api/v1/portfolio/import") && r.request().method() === "POST",
        { timeout: 45_000 },
      ),
      page.locator('input[type="file"]').first().setInputFiles(csv),
    ]);

    // The dry-run endpoint must answer cleanly...
    expect(importResp.status(), "dry-run import did not return 200").toBe(200);

    // ...and the parsed-rows preview should render (the chip reads "N parsed").
    await expect(
      page.getByText(/\d+\s+parsed/i).first(),
      "import preview did not render",
    ).toBeVisible({ timeout: 20_000 });

    // Make sure we did NOT accidentally persist, and that rows actually parsed.
    const payload = await importResp.json().catch(() => ({}) as Record<string, unknown>);
    expect(payload.dry_run, "import was not a dry-run").not.toBe(false);
    expect(Number(payload.imported ?? 0), "no rows parsed from the CSV").toBeGreaterThan(0);

    await recordIssues(testInfo, "/portfolio [import dry-run]", issues);
    expect(issues.pageErrors).toEqual([]);
  });
});
