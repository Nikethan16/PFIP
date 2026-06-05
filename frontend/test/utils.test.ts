import { describe, it, expect } from "vitest";

import {
  cn,
  DISPLAY_TZ,
  formatIST,
  formatISTDate,
  formatINR,
  formatPct,
  confidenceTone,
} from "@/lib/utils";

describe("cn", () => {
  it("joins multiple class strings", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("drops falsy/conditional values", () => {
    expect(cn("a", false && "b", null, undefined, "c")).toBe("a c");
  });

  it("resolves conflicting tailwind utilities (last wins)", () => {
    // tailwind-merge collapses p-2 + p-4 to the later padding.
    expect(cn("p-2", "p-4")).toBe("p-4");
  });
});

describe("DISPLAY_TZ", () => {
  it("is the India timezone", () => {
    expect(DISPLAY_TZ).toBe("Asia/Kolkata");
  });
});

describe("formatINR", () => {
  it("returns an em-dash for null/undefined/NaN", () => {
    expect(formatINR(null)).toBe("—");
    expect(formatINR(undefined)).toBe("—");
    expect(formatINR(Number.NaN)).toBe("—");
  });

  it("formats zero", () => {
    const out = formatINR(0);
    expect(out).toContain("0");
    // Currency style includes the rupee symbol.
    expect(out).toContain("₹");
  });

  it("formats positive amounts with lakh/crore (en-IN) grouping", () => {
    // 1,00,000 in the Indian numbering system (groups of 2 after the first 3).
    const out = formatINR(100000);
    expect(out).toContain("1,00,000");
  });

  it("formats negative amounts with a leading minus", () => {
    const out = formatINR(-1500);
    expect(out).toContain("-");
    expect(out).toContain("1,500");
  });

  it("rounds to whole rupees by default (fractionDigits = 0)", () => {
    const out = formatINR(1234.56);
    // maximumFractionDigits: 0 → no decimal point in the output.
    expect(out).not.toContain(".");
    expect(out).toContain("1,235");
  });

  it("honours an explicit fractionDigits argument", () => {
    const out = formatINR(1234.5, 2);
    expect(out).toContain("1,234.5");
  });
});

describe("formatPct", () => {
  it("returns an em-dash for null/undefined/NaN", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(undefined)).toBe("—");
    expect(formatPct(Number.NaN)).toBe("—");
  });

  it("prefixes positive values with '+' and a percent sign", () => {
    expect(formatPct(2.5)).toBe("+2.50%");
  });

  it("does NOT prefix zero with '+'", () => {
    expect(formatPct(0)).toBe("0.00%");
  });

  it("keeps the native minus sign for negatives (no extra '+')", () => {
    expect(formatPct(-3.1)).toBe("-3.10%");
  });

  it("respects a custom fractionDigits value", () => {
    expect(formatPct(1.23456, 1)).toBe("+1.2%");
    expect(formatPct(5, 0)).toBe("+5%");
  });

  it("treats the value as already-a-percentage (does not divide by 100)", () => {
    // 12.5 means "12.5%", not "1250%".
    expect(formatPct(12.5)).toBe("+12.50%");
  });
});

describe("formatIST", () => {
  it("returns an em-dash for an unparseable date string", () => {
    expect(formatIST("not-a-date")).toBe("—");
  });

  it("renders an IST suffix by default", () => {
    const out = formatIST("2026-01-15T00:00:00Z");
    expect(out).toContain("IST");
  });

  it("shifts UTC into IST (+5:30)", () => {
    // 2026-01-15T00:00:00Z → 05:30 IST on the same day.
    const out = formatIST("2026-01-15T00:00:00Z");
    expect(out).toContain("05:30");
    expect(out).toContain("15 Jan 2026");
  });

  it("accepts a Date instance as well as a string", () => {
    const out = formatIST(new Date("2026-01-15T00:00:00Z"));
    expect(out).toContain("05:30");
  });

  it("honours a custom pattern", () => {
    const out = formatIST("2026-01-15T00:00:00Z", "yyyy-MM-dd");
    expect(out).toBe("2026-01-15");
  });
});

describe("formatISTDate", () => {
  it("renders the short 'dd MMM' form", () => {
    // 2026-04-20T18:30:00Z → 21 Apr in IST (crosses midnight: 00:00 next day).
    expect(formatISTDate("2026-04-20T18:30:00Z")).toBe("21 Apr");
  });
});

describe("confidenceTone", () => {
  it("returns emerald at/above 70", () => {
    expect(confidenceTone(70)).toBe("emerald");
    expect(confidenceTone(100)).toBe("emerald");
  });

  it("returns amber in [45, 70)", () => {
    expect(confidenceTone(45)).toBe("amber");
    expect(confidenceTone(69)).toBe("amber");
  });

  it("returns red below 45", () => {
    expect(confidenceTone(44)).toBe("red");
    expect(confidenceTone(0)).toBe("red");
  });
});
