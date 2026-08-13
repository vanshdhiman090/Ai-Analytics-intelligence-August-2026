import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const orders = path.join(here, "fixtures", "orders.csv");
const customers = path.join(here, "fixtures", "customers.csv");

function dataset(id, filename, rows, candidateKey) {
  return {
    dataset_id: id, filename, rows, columns: 2, candidate_keys: [candidateKey],
    profile: { row_count: rows, column_count: 2, duplicate_row_count: 0, all_null_columns: [], constant_columns: [], columns: {} },
    preview: [],
  };
}

async function mockApi(page, options = {}) {
  let upload = 0;
  let submittedSession = null;
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/sessions" && request.method() === "GET") return route.fulfill({ json: { sessions: [] } });
    if (url.pathname === "/evaluations/latest") return route.fulfill({ json: { summary: { release_ready: true, weighted_score: 1, passed_count: 27, case_count: 27, category_scores: { calculation: 1 } } } });
    if (url.pathname === "/datasets" && request.method() === "POST") {
      if (options.uploadError) return route.fulfill({ status: 400, json: { detail: options.uploadError } });
      upload += 1;
      return route.fulfill({ status: 201, json: { dataset_id: `d${upload}`, filename: upload === 1 ? "orders.csv" : "customers.csv", profile: {}, preview: [] } });
    }
    if (url.pathname === "/data-model/inspect") {
      const relationship = { relationship_id: "d1:d2:customer_id", left_dataset_id: "d1", left_filename: "orders.csv", right_dataset_id: "d2", right_filename: "customers.csv", left_key: "customer_id", right_key: "customer_id", cardinality: "many_to_one", left_unique: false, right_unique: true, left_match_rate: 1, right_match_rate: 1, overlapping_keys: 2, confidence_score: 1, recommended: true, blocked: false, warnings: [], join_type: "left" };
      return route.fulfill({ json: { model_status: "ready", datasets: [dataset("d1", "orders.csv", 2, "order_id"), dataset("d2", "customers.csv", 2, "customer_id")], relationships: [relationship], proposed_joins: [relationship], unconnected_dataset_ids: [] } });
    }
    if (url.pathname === "/sessions" && request.method() === "POST") {
      submittedSession = request.postDataJSON();
      return route.fulfill({ status: 202, json: { session_id: "session-1", status: "queued" } });
    }
    if (url.pathname === "/sessions/session-1") return route.fulfill({ json: { session_id: "session-1", status: "running", current_stage: "ask", run_attempt: 1 } });
    return route.fulfill({ status: 404, json: { detail: `Unhandled test route ${url.pathname}` } });
  });
  return () => submittedSession;
}

test("multi-file upload, model review, and approval complete without runtime errors", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const submitted = await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Turn evidence into decisions" })).toBeVisible();
  await page.getByRole("button", { name: "+ New analysis", exact: true }).click();
  await page.getByPlaceholder(/Which customer segments and products/).fill("Which customer segments drive revenue?");
  await page.getByRole("button", { name: "Continue to data" }).click();
  await page.locator('input[type="file"]').setInputFiles([orders, customers]);
  await expect(page.getByText("2 files selected")).toBeVisible();
  await page.getByRole("button", { name: "Build and review data model" }).click();
  await expect(page.getByRole("heading", { name: "2 connected data sources" })).toBeVisible();
  await expect(page.getByText("Approved for model")).toBeVisible();
  await page.getByRole("button", { name: "Approve model and continue" }).click();
  await expect(page.getByRole("heading", { name: "Confirm the analysis contract" })).toBeVisible();
  await page.getByRole("button", { name: "Create project and start" }).click();
  await expect(page.getByRole("heading", { name: "Working through the ask phase" })).toBeVisible();
  expect(submitted()).toEqual({ dataset_ids: ["d1", "d2"], joins: [{ relationship_id: "d1:d2:customer_id" }], rough_prompt: "Which customer segments drive revenue?", business_question: "Which customer segments drive revenue?", analysis_objectives: ["drivers", "trends", "segments"], workflow_mode: "fast" });
  expect(pageErrors).toEqual([]);
});

test("unsupported files and backend upload failures are explained", async ({ page }) => {
  await mockApi(page, { uploadError: "The CSV is damaged or uses an unsupported structure." });
  await page.goto("/");
  await page.getByRole("button", { name: "+ New analysis", exact: true }).click();
  await page.getByPlaceholder(/Which customer segments and products/).fill("Summarize revenue performance");
  await page.getByRole("button", { name: "Continue to data" }).click();
  await page.locator('input[type="file"]').setInputFiles(orders);
  await page.getByRole("button", { name: "Review dataset" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "CSV is damaged" })).toContainText("CSV is damaged");
});

test("analysis history remains usable when optional accuracy status is unavailable", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/sessions") return route.fulfill({ json: { sessions: [{ session_id: "done-1", status: "complete", current_stage: "complete", business_task: "Revenue review", updated_at: "2026-08-08T10:00:00Z" }] } });
    if (url.pathname === "/evaluations/latest") return route.abort();
    if (url.pathname === "/sessions/done-1") return route.fulfill({ json: { session_id: "done-1", status: "complete", current_stage: "complete", business_task: "Revenue review", result: { summary: "Revenue is stable.", findings: [], recommendations: [], limitations: [] }, artifacts: [], actions: [] } });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Revenue review/ })).toBeVisible();
  await page.getByRole("button", { name: /Revenue review/ }).click();
  await expect(page.getByText("Revenue is stable.")).toBeVisible();
});
