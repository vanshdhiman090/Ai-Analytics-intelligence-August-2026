import { defineConfig, devices } from "@playwright/test";

process.env.PLAYWRIGHT_APP_PORT = "3012";
process.env.NEXT_DIST_DIR = ".next-e2e-demo";
process.env.NEXT_PUBLIC_RECRUITER_DEMO_MODE = "true";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "recruiter-demo.spec.mjs",
  globalSetup: "./e2e/global-setup.mjs",
  fullyParallel: false,
  forbidOnly: true,
  retries: 1,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3012",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
