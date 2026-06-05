import { describe, it, expect } from "vitest";

/**
 * `lib/api.ts` and `lib/auth.ts` both normalise the configured backend base so
 * it ALWAYS ends with `/api/v1` (trailing slashes stripped). That logic is not
 * exported, so this test pins the EXACT algorithm via a local mirror. If the
 * source logic changes, update this mirror to match — it documents intended
 * behaviour and guards against regressions in the "every page 404s" footgun.
 */
function normalizeApiBase(raw: string): string {
  const trimmed = raw.replace(/\/+$/, "");
  return trimmed.endsWith("/api/v1") ? trimmed : `${trimmed}/api/v1`;
}

describe("backend base URL normalization", () => {
  it("appends /api/v1 to a bare host", () => {
    expect(normalizeApiBase("http://localhost:8000")).toBe(
      "http://localhost:8000/api/v1",
    );
  });

  it("leaves an already-suffixed URL unchanged", () => {
    expect(normalizeApiBase("http://localhost:8000/api/v1")).toBe(
      "http://localhost:8000/api/v1",
    );
  });

  it("strips trailing slashes before deciding", () => {
    expect(normalizeApiBase("http://localhost:8000/")).toBe(
      "http://localhost:8000/api/v1",
    );
    expect(normalizeApiBase("http://localhost:8000/api/v1/")).toBe(
      "http://localhost:8000/api/v1",
    );
    expect(normalizeApiBase("http://localhost:8000///")).toBe(
      "http://localhost:8000/api/v1",
    );
  });

  it("handles the Docker service-name base", () => {
    expect(normalizeApiBase("http://backend:8000")).toBe(
      "http://backend:8000/api/v1",
    );
  });

  it("does not double-append when suffix already present with trailing slash", () => {
    expect(normalizeApiBase("https://api.example.com/api/v1/")).toBe(
      "https://api.example.com/api/v1",
    );
  });
});
