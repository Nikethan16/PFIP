import type {
  Reporter,
  TestCase,
  TestResult,
  FullResult,
} from "@playwright/test/reporter";
import * as fs from "node:fs";
import * as path from "node:path";

/**
 * Aggregates the per-test "issues" attachments into one human-readable findings
 * file (e2e/report/FINDINGS.md) plus a console summary — so you get a one-glance
 * list of what's broken: which page, which API call, which data/schema mismatch.
 */

interface Issues {
  label: string;
  failedRequests: { url: string; status: number; method: string }[];
  schemaFailures: string[];
  pageErrors: string[];
  consoleErrors: string[];
}

interface Row {
  title: string;
  status: string;
  error?: string;
  issues?: Issues;
}

function shortenUrl(url: string): string {
  const i = url.indexOf("/api/v1/");
  return i >= 0 ? url.slice(i) : url;
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function hasIssues(i?: Issues): boolean {
  return (
    !!i &&
    (i.failedRequests.length > 0 ||
      i.schemaFailures.length > 0 ||
      i.pageErrors.length > 0 ||
      i.consoleErrors.length > 0)
  );
}

export default class IssueReporter implements Reporter {
  private rows: Row[] = [];

  onTestEnd(test: TestCase, result: TestResult): void {
    const att = result.attachments.find((a) => a.name === "issues");
    let issues: Issues | undefined;
    if (att?.body) {
      try {
        issues = JSON.parse(att.body.toString("utf-8")) as Issues;
      } catch {
        /* ignore malformed attachment */
      }
    }
    this.rows.push({
      title: test.title,
      status: result.status,
      error: result.error?.message,
      issues,
    });
  }

  onEnd(result: FullResult): void {
    const lines: string[] = [];
    lines.push("# PFIP E2E findings", "");
    lines.push(
      `Run finished: **${result.status}** · ${new Date().toISOString()}`,
      "",
    );

    const problems = this.rows.filter(
      (r) => r.status !== "passed" || hasIssues(r.issues),
    );

    if (problems.length === 0) {
      lines.push(
        "✅ No issues found — every page loaded with real data and all flows passed.",
      );
    } else {
      const passedCount = this.rows.filter((r) => r.status === "passed").length;
      lines.push(
        `**${passedCount}/${this.rows.length} checks passed.** ${problems.length} item(s) need attention:`,
        "",
      );
      for (const p of problems) {
        const icon = p.status === "passed" ? "⚠️" : "❌";
        lines.push(`### ${icon} ${p.title} — _${p.status}_`);
        if (p.status !== "passed" && p.error) {
          lines.push(`- 🧪 assertion: ${truncate(p.error.replace(/\s+/g, " "), 240)}`);
        }
        const i = p.issues;
        if (i) {
          for (const f of i.failedRequests)
            lines.push(`- 🔴 API ${f.status} ${f.method} \`${shortenUrl(f.url)}\``);
          if (i.schemaFailures.length)
            lines.push(
              `- 🟠 ${i.schemaFailures.length} data/schema mismatch(es) — page shows no/partial data`,
            );
          for (const e of i.pageErrors) lines.push(`- 💥 JS error: ${truncate(e, 200)}`);
          for (const c of i.consoleErrors)
            lines.push(`- 🟡 console: ${truncate(c, 160)}`);
        }
        lines.push("");
      }
    }

    const outDir = path.join("e2e", "report");
    fs.mkdirSync(outDir, { recursive: true });
    const body = lines.join("\n");
    fs.writeFileSync(path.join(outDir, "FINDINGS.md"), body, "utf-8");
    // eslint-disable-next-line no-console
    console.log("\n" + body + "\n");
  }
}
