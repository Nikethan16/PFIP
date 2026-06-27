import { test as setup, expect } from "@playwright/test";
import * as fs from "node:fs";

/**
 * Logs in once via the real NextAuth credentials form and saves the browser
 * session (cookies + storage) to e2e/.auth/user.json. Every other test reuses
 * that state, so we authenticate exactly once per run.
 */

const AUTH_FILE = "e2e/.auth/user.json";

setup("authenticate", async ({ page }) => {
  const email = process.env.PFIP_E2E_EMAIL;
  const password = process.env.PFIP_E2E_PASSWORD;
  if (!email || !password) {
    throw new Error(
      "Missing creds: set PFIP_E2E_EMAIL and PFIP_E2E_PASSWORD " +
        "(e.g. in frontend/e2e/.env.local). See e2e/README.md.",
    );
  }

  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();

  // On success the app router pushes to the callbackUrl ("/"). Wait until we're
  // off the login page; if creds are wrong we stay on /login with a toast.
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 30_000,
  });
  await expect(page, "login did not navigate away from /login").not.toHaveURL(
    /\/login/,
  );

  fs.mkdirSync("e2e/.auth", { recursive: true });
  await page.context().storageState({ path: AUTH_FILE });
});
