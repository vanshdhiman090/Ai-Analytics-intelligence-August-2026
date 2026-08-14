import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

function sourceFingerprint() {
  const roots = ["src", "package.json", "next.config.mjs", "playwright.config.mjs", "e2e/workspace.spec.mjs"];
  const files = [];
  function collect(item) {
    const full = path.resolve(item);
    if (!fs.existsSync(full)) return;
    if (fs.statSync(full).isDirectory()) {
      for (const child of fs.readdirSync(full)) collect(path.join(item, child));
    } else if (/\.(js|mjs|css|json)$/.test(item)) files.push(item.replaceAll("\\", "/"));
  }
  roots.forEach(collect);
  const hash = crypto.createHash("sha256");
  for (const file of files.sort()) {
    hash.update(file); hash.update("\0"); hash.update(fs.readFileSync(path.resolve(file))); hash.update("\0");
  }
  return hash.digest("hex");
}

export default class ReleaseReporter {
  onBegin(_config, suite) {
    this.suite = suite;
    this.total = suite.allTests().length;
  }

  onEnd(result) {
    const failures = [];
    for (const test of this.suite?.allTests() || []) {
      const last = test.results?.at(-1);
      if (last && !["passed", "skipped"].includes(last.status)) {
        failures.push({ title: test.title, status: last.status, error: last.error?.message?.split("\n")[0] || "Unknown failure" });
      }
    }
    const passed = result.status === "passed";
    const payload = {
      suite_version: "1.0",
      generated_at: new Date().toISOString(),
      status: passed ? "passed" : "failed",
      release_ready: passed,
      case_count: this.total || 0,
      passed_count: passed ? this.total || 0 : Math.max(0, (this.total || 0) - failures.length),
      failures,
      source_fingerprint: sourceFingerprint(),
    };
    const output = path.resolve(process.env.PLAYWRIGHT_RELEASE_REPORT || path.join("e2e", "reports", "latest.json"));
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(payload, null, 2));
  }
}
