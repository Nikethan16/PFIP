import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * DATA-quality monitor (not just HTTP 200). This is the suite that would have
 * caught the failures a green deploy hid: stale equities, empty per-asset news,
 * a dead chat LLM, missing source-health. It logs in via the API and asserts the
 * data is actually FRESH and PRESENT.
 *
 * Run against the live VM (default baseURL):  pnpm test:e2e data-freshness
 * Intended as a nightly monitor — it legitimately fails when data goes stale,
 * so it is NOT part of the deploy gate.
 */

const EMAIL = process.env.PFIP_E2E_EMAIL;
const PASSWORD = process.env.PFIP_E2E_PASSWORD;

// Max acceptable age (days) of the freshest bar per class. Generous for
// weekends/holidays; trips on the real 5–7 day staleness we saw.
const SLA_DAYS: Record<string, number> = {
  "BTC-USD": 2,
  "RELIANCE.NS": 5,
  "AAPL": 5,
};

async function login(request: APIRequestContext): Promise<string> {
  expect(EMAIL && PASSWORD, "set PFIP_E2E_EMAIL / PFIP_E2E_PASSWORD").toBeTruthy();
  const res = await request.post("/api/v1/auth/login", {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(res.ok(), `login failed: ${res.status()}`).toBeTruthy();
  return (await res.json()).token as string;
}

function ageDays(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / 86_400_000;
}

test.describe("data freshness + presence (live monitor)", () => {
  test("market data is fresh per asset class", async ({ request }) => {
    const token = await login(request);
    const headers = { Authorization: `Bearer ${token}` };
    for (const [symbol, sla] of Object.entries(SLA_DAYS)) {
      const r = await request.get(
        `/api/v1/assets/${encodeURIComponent(symbol)}/candles?timeframe=1d&limit=3000`,
        { headers },
      );
      expect(r.ok(), `${symbol} candles HTTP ${r.status()}`).toBeTruthy();
      const bars = (await r.json()) as Array<{ time: string }>;
      expect(bars.length, `${symbol} has no candles`).toBeGreaterThan(0);
      const age = ageDays(bars[bars.length - 1].time);
      expect(age, `${symbol} latest bar is ${age.toFixed(1)}d old (SLA ${sla}d)`).toBeLessThan(
        sla,
      );
    }
  });

  test("per-asset news is wired (entity-linking surfaces stories)", async ({ request }) => {
    const token = await login(request);
    const headers = { Authorization: `Bearer ${token}` };
    // Sum across a few liquid names; at least one should carry linked news once
    // the entity-linker has run with the alias map.
    let total = 0;
    for (const sym of ["BTC-USD", "RELIANCE.NS", "AAPL", "NVDA"]) {
      const r = await request.get(`/api/v1/assets/${encodeURIComponent(sym)}/news?limit=20`, {
        headers,
      });
      expect(r.ok()).toBeTruthy();
      total += ((await r.json()) as unknown[]).length;
    }
    expect(total, "no per-asset news linked on any tracked symbol").toBeGreaterThan(0);
  });

  test("chat returns a real LLM answer (not a provider-failure stub)", async ({ request }) => {
    const token = await login(request);
    const res = await request.post("/api/v1/agent/chat", {
      headers: { Authorization: `Bearer ${token}` },
      data: { message: "Reply with the single word: pong." },
      timeout: 60_000,
    });
    expect(res.ok(), `chat HTTP ${res.status()}`).toBeTruthy();
    const body = await res.text();
    expect(
      body.toLowerCase(),
      "chat returned an LLM-unavailable stub — provider routing/fallback is broken",
    ).not.toContain("llm unavailable");
    expect(body, "chat stream produced no token events").toContain("event: token");
  });

  test("source health is being recorded (observability is live)", async ({ request }) => {
    const token = await login(request);
    const r = await request.get("/api/v1/health/sources", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.ok()).toBeTruthy();
    const body = (await r.json()) as { summary?: { total?: number } };
    expect(
      body.summary?.total ?? 0,
      "source_health is empty — pipeline isn't recording per-source health yet",
    ).toBeGreaterThan(0);
  });
});
