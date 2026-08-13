import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 1,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: [["line"], ["./e2e/release-reporter.mjs"]],
  use: {
    baseURL: "http://127.0.0.1:3011",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "set NEXT_DIST_DIR=.next-e2e&& npm run dev -- -p 3011 -H 127.0.0.1",
    url: "http://127.0.0.1:3011",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
