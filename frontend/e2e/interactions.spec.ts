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

  test("chat: ask the agent and get a streamed answer", async ({
    page,
    issues,
  }, testInfo) => {
    await page.goto("/chat", { waitUntil: "domcontentloaded" });

    const input = page.getByRole("textbox", { name: /chat input/i });
    await expect(input, "chat input not found").toBeVisible();

    const log = page.getByRole("log");
    const question = "In one sentence, what is rupee cost averaging?";
    await input.fill(question);
    await page.getByRole("button", { name: /^send$/i }).click();

    // The user's message should echo into the transcript (the empty-state text
    // clears once a turn exists)...
    await expect(log, "user message did not appear in transcript").toContainText(
      "rupee cost averaging",
      { timeout: 20_000 },
    );

    // ...and the assistant reply should stream in. Baseline is captured AFTER
    // the echo (so the cleared empty-state text doesn't skew it); the transcript
    // then grows as tokens arrive.
    const afterSend = (await log.innerText().catch(() => "")).length;
    await expect
      .poll(async () => (await log.innerText().catch(() => "")).length, {
        message: "assistant response never streamed in",
        timeout: 70_000,
        intervals: [1000, 2000, 3000],
      })
      .toBeGreaterThan(afterSend + 40);

    await recordIssues(testInfo, "/chat [ask]", issues);
    expect(issues.pageErrors, "JS errors during chat").toEqual([]);
    expect(issues.failedRequests, "failed API calls during chat").toEqual([]);
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
