import { describe, it, expect } from "vitest";

import { config } from "@/middleware";

/**
 * Smoke test for the route-guard matcher. The matcher is a Next.js
 * path-to-regexp-style string; here we compile its inner negative-lookahead
 * group into a RegExp and assert which paths the auth guard applies to.
 *
 * Matcher source:
 *   "/((?!login|api/auth|_next/static|_next/image|favicon.ico|.*\\..*).*)"
 */
const matcher = Array.isArray(config.matcher) ? config.matcher[0] : config.matcher;

// Next.js anchors the matcher; emulate full-path matching here.
const re = new RegExp(`^${matcher}$`);

function isGuarded(path: string): boolean {
  return re.test(path);
}

describe("middleware matcher", () => {
  it("exposes a single matcher entry", () => {
    expect(Array.isArray(config.matcher)).toBe(true);
    expect(config.matcher).toHaveLength(1);
    expect(matcher).toContain("(?!");
  });

  it("GUARDS application routes", () => {
    expect(isGuarded("/portfolio")).toBe(true);
    expect(isGuarded("/signals")).toBe(true);
    expect(isGuarded("/journal")).toBe(true);
    expect(isGuarded("/")).toBe(true);
  });

  it("EXCLUDES the login page", () => {
    expect(isGuarded("/login")).toBe(false);
  });

  it("EXCLUDES NextAuth's own API routes", () => {
    expect(isGuarded("/api/auth/session")).toBe(false);
    expect(isGuarded("/api/auth/callback/credentials")).toBe(false);
  });

  it("EXCLUDES Next.js build assets", () => {
    expect(isGuarded("/_next/static/chunk.js")).toBe(false);
    expect(isGuarded("/_next/image")).toBe(false);
  });

  it("EXCLUDES static files (any path with an extension)", () => {
    expect(isGuarded("/favicon.ico")).toBe(false);
    expect(isGuarded("/logo.png")).toBe(false);
    expect(isGuarded("/robots.txt")).toBe(false);
  });

  it("still GUARDS a non-auth /api route (e.g. would-be proxy)", () => {
    // Only `api/auth` is excluded; other api paths remain protected.
    expect(isGuarded("/api/portfolio")).toBe(true);
  });
});
