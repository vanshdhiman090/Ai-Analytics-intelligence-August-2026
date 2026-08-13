import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const revenueFile = path.join(here, "fixtures", "rca-revenue.csv");

const DATASET_ID = "11111111-1111-4111-8111-111111111111";
const INVESTIGATION_ID = "22222222-2222-4222-8222-222222222222";

function profileColumn(name, semanticType, uniqueCount, extras = {}) {
  return { name, dtype: "object", semantic_type: semanticType, null_count: 0, null_pct: 0, unique_count: uniqueCount, sample_values: [], ...extras };
}

function datasetResponse() {
  return {
    dataset_id: DATASET_ID,
    filename: "rca-revenue.csv",
    size_bytes: 9216,
    profile: {
      row_count: 8,
      column_count: 7,
      duplicate_row_count: 0,
      all_null_columns: [],
      constant_columns: ["constant_field"],
      columns: {
        date: profileColumn("date", "datetime", 2, { date_semantics: { status: "CONFIDENT_DATE_FORMAT", min_date: "2026-01-01T00:00:00", max_date: "2026-02-01T00:00:00", missing_months: [] } }),
        revenue: profileColumn("revenue", "numeric", 7),
        country: profileColumn("country", "categorical", 3),
        device: profileColumn("device", "categorical", 2),
        customer_type: profileColumn("customer_type", "categorical", 2),
        order_id: profileColumn("order_id", "text", 8),
        constant_field: profileColumn("constant_field", "categorical", 1),
      },
    },
    preview: [],
  };
}

function filter(dimension, segment) {
  return { dimension, segment };
}

function successResponse(overrides = {}) {
  const base = {
    api_version: "1.0",
    investigation_id: INVESTIGATION_ID,
    kpi_movement: { name: "Revenue", unit: "EUR", baseline_period: "2026-01", comparison_period: "2026-02", baseline_value: 100000, comparison_value: 85000, signed_change: -15000, evidence_refs: ["EV1"] },
    investigation_path: [
      { depth: 1, source_scope: [], target_scope: [filter("country", "Germany")], dimension: "country", segment: "Germany", baseline_value: 60000, comparison_value: 49000, parent_movement: -15000, segment_movement: -11000, local_contribution_pct: 73.333, global_contribution_pct: 73.333, evidence_strength: "strong", evidence_refs: ["EV2"] },
      { depth: 2, source_scope: [filter("country", "Germany")], target_scope: [filter("country", "Germany"), filter("device", "Mobile")], dimension: "device", segment: "Mobile", baseline_value: 33000, comparison_value: 24500, parent_movement: -11000, segment_movement: -8500, local_contribution_pct: 77.273, global_contribution_pct: 56.667, evidence_strength: "strong", evidence_refs: ["EV3"] },
      { depth: 3, source_scope: [filter("country", "Germany"), filter("device", "Mobile")], target_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], dimension: "customer_type", segment: "Returning", baseline_value: 26000, comparison_value: 16500, parent_movement: -8500, segment_movement: -9500, local_contribution_pct: 111.765, global_contribution_pct: 63.333, evidence_strength: "strong", evidence_refs: ["EV4"] },
    ],
    leading_contributor: { source_scope: [filter("country", "Germany"), filter("device", "Mobile")], target_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], dimension: "customer_type", segment: "Returning", baseline_value: 26000, comparison_value: 16500, signed_change: -9500, local_contribution_pct: 111.765, global_contribution_pct: 63.333, evidence_strength: "strong", evidence_refs: ["EV4"] },
    selected_decomposition: { source_scope: [filter("country", "Germany"), filter("device", "Mobile")], dimension: "customer_type", parent_movement: -8500, dimension_net_movement: -8500, leading_segment_movement: -9500, remaining_segment_movement: 1000, downward_pressure: -10500, positive_offsets: 2000, reconciliation_residual: 0, reconciles: true, evidence_refs: ["EV4"] },
    conclusion: { claim: "leading_tested_contributor", readiness: { status: "ready_with_caveats", reason: null }, robustness: { status: "not_verified", applies_to_selected_target: false }, terminal_status: "completed_with_caveats", caveats: ["material_offsets", "leading_segment_remainder", "robustness_applies_to_upstream_scope_only"], recommended_next_action: "review_large_offsets", evidence_refs: ["EV4"] },
    data_quality: { status: "pass", issues: [] },
    supporting_evidence: [
      { evidence_ref: "EV1", kind: "kpi_movement", source_scope: [], target_scope: [], dimension: null, segment: null, baseline_value: 100000, comparison_value: 85000, signed_change: -15000, local_contribution_pct: null, global_contribution_pct: null, quality_code: null },
      { evidence_ref: "EV2", kind: "contribution", source_scope: [], target_scope: [filter("country", "Germany")], dimension: "country", segment: "Germany", baseline_value: 60000, comparison_value: 49000, signed_change: -11000, local_contribution_pct: 73.333, global_contribution_pct: 73.333, quality_code: null },
      { evidence_ref: "EV3", kind: "contribution", source_scope: [filter("country", "Germany")], target_scope: [filter("country", "Germany"), filter("device", "Mobile")], dimension: "device", segment: "Mobile", baseline_value: 33000, comparison_value: 24500, signed_change: -8500, local_contribution_pct: 77.273, global_contribution_pct: 56.667, quality_code: null },
      { evidence_ref: "EV4", kind: "contribution", source_scope: [filter("country", "Germany"), filter("device", "Mobile")], target_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], dimension: "customer_type", segment: "Returning", baseline_value: 26000, comparison_value: 16500, signed_change: -9500, local_contribution_pct: 111.765, global_contribution_pct: 63.333, quality_code: null },
    ],
  };
  return { ...base, ...overrides };
}

function abstentionResponse() {
  return successResponse({
    investigation_path: [],
    leading_contributor: null,
    selected_decomposition: null,
    conclusion: { claim: "data_quality_abstention", readiness: { status: "not_ready", reason: "data_quality" }, robustness: { status: "abstained", applies_to_selected_target: false }, terminal_status: "blocked_by_data_quality", caveats: ["insufficient_evidence"], recommended_next_action: "improve_data_quality", evidence_refs: ["EV1", "EV2"] },
    data_quality: { status: "blocked", issues: [{ code: "comparison_coverage_incomplete", severity: "blocking", source_scope: [], affects_selected_target: true, evidence_refs: ["EV2"] }] },
    supporting_evidence: [
      { evidence_ref: "EV1", kind: "kpi_movement", source_scope: [], target_scope: [], dimension: null, segment: null, baseline_value: 100000, comparison_value: null, signed_change: null, local_contribution_pct: null, global_contribution_pct: null, quality_code: null },
      { evidence_ref: "EV2", kind: "data_quality", source_scope: [], target_scope: [], dimension: null, segment: null, baseline_value: null, comparison_value: null, signed_change: null, local_contribution_pct: null, global_contribution_pct: null, quality_code: "comparison_coverage_incomplete" },
    ],
  });
}

function inconclusiveResponse() {
  return successResponse({
    investigation_path: [], leading_contributor: null, selected_decomposition: null,
    conclusion: { claim: "inconclusive", readiness: { status: "not_ready", reason: "insufficient_evidence" }, robustness: { status: "not_verified", applies_to_selected_target: false }, terminal_status: "no_material_driver", caveats: ["no_material_driver"], recommended_next_action: "expand_candidate_dimensions", evidence_refs: ["EV1"] },
    data_quality: { status: "pass", issues: [] },
    supporting_evidence: [{ evidence_ref: "EV1", kind: "kpi_movement", source_scope: [], target_scope: [], dimension: null, segment: null, baseline_value: 100000, comparison_value: 85000, signed_change: -15000, local_contribution_pct: null, global_contribution_pct: null, quality_code: null }],
  });
}

async function mockApi(page, options = {}) {
  const payloads = [];
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/datasets" && request.method() === "POST") {
      if (options.uploadError) return route.fulfill({ status: 400, json: { detail: options.uploadError } });
      return route.fulfill({ status: 201, json: datasetResponse() });
    }
    if (url.pathname === `/datasets/${DATASET_ID}` && request.method() === "DELETE") return route.fulfill({ status: 204, body: "" });
    if (url.pathname === "/v1/rca/investigations" && request.method() === "POST") {
      payloads.push(request.postDataJSON());
      if (options.abortRca) return route.abort();
      if (options.delay) await new Promise((resolve) => setTimeout(resolve, options.delay));
      if (options.rcaError) return route.fulfill({ status: options.rcaError.status, headers: { "X-Request-ID": options.rcaError.body.error.request_id }, json: options.rcaError.body });
      return route.fulfill({ status: 200, json: options.rcaResponse || successResponse() });
    }
    return route.fulfill({ status: 404, json: { detail: `Unhandled test route ${url.pathname}` } });
  });
  return payloads;
}

async function uploadAndConfigure(page, { keyboardDimensions = false } = {}) {
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.getByRole("heading", { name: "Define the additive KPI" })).toBeVisible();
  await page.getByLabel("Unit optional").fill("EUR");
  await page.getByLabel("Baseline period", { exact: true }).fill("2026-01");
  await page.getByLabel("Comparison period", { exact: true }).fill("2026-02");
  for (const name of ["Country", "Device", "Customer Type"]) {
    const checkbox = page.locator("label.dimension-option", { hasText: name }).locator("input");
    if (keyboardDimensions) { await checkbox.focus(); await page.keyboard.press("Space"); }
    else await checkbox.check();
  }
  await page.getByRole("button", { name: "Review investigation" }).click();
  await expect(page.getByRole("heading", { name: "Confirm the bounded investigation" })).toBeVisible();
}

async function runInvestigation(page) {
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.getByTestId("rca-result")).toBeVisible();
}

function assertSemanticSafety(text) {
  const normalized = text.toLowerCase().replace("descriptive contribution path — not a causal chain.", "");
  for (const phrase of ["confirmed root cause", "proven root cause", "caused by", "causal chain", "unexplained movement"]) expect(normalized).not.toContain(phrase);
}

test("single-dataset RCA flow submits the exact public request and renders signed evidence safely", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const payloads = await mockApi(page, { delay: 150 });
  await uploadAndConfigure(page);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.getByRole("heading", { name: "Testing the approved KPI movement" })).toBeVisible();
  await expect(page.getByTestId("rca-result")).toBeVisible();

  expect(payloads).toEqual([{
    dataset_id: DATASET_ID,
    goal: "Investigate why Revenue changed between 2026-01 and 2026-02 within the approved dimensions.",
    kpi: { name: "Revenue", metric_column: "revenue", time_column: "date", time_grain: "month", aggregation: "sum", unit: "EUR" },
    baseline_period: "2026-01",
    comparison_period: "2026-02",
    candidate_dimensions: ["country", "device", "customer_type"],
  }]);
  await expect(page.getByRole("heading", { name: "Tested investigation path" })).toBeVisible();
  const pathNodes = page.locator(".path-node");
  await expect(pathNodes.nth(1)).toContainText("Germany");
  await expect(pathNodes.nth(2)).toContainText("Mobile");
  await expect(pathNodes.nth(3)).toContainText("Returning");
  await expect(page.getByRole("heading", { name: "Leading tested contributor", exact: true })).toBeVisible();
  await expect(page.getByText("+111.8%", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".decomposition-grid div", { hasText: "Positive offsets" })).toContainText("+");
  await expect(page.getByText("Remaining movement across other segments in this decomposition", { exact: true })).toBeVisible();
  await expect(page.locator(".decomposition-grid dt", { hasText: "Reconciliation tie-out" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Not verified at the selected target" })).toBeVisible();
  await expect(page.locator(".incident-change")).toContainText("-15%");
  assertSemanticSafety(await page.locator("body").innerText());
  expect(pageErrors).toEqual([]);
});

test("target-applicable robustness is descriptive and does not imply certainty", async ({ page }) => {
  const result = successResponse({ conclusion: { ...successResponse().conclusion, claim: "robust_descriptive_explanation", robustness: { status: "robust", applies_to_selected_target: true }, caveats: [] } });
  await mockApi(page, { rcaResponse: result });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.locator(".status-card.robustness")).toContainText("Robust descriptive explanation");
  await expect(page.locator(".status-card.robustness")).toContainText("not causal certainty");
  assertSemanticSafety(await page.locator("body").innerText());
});

test("downstream data-quality limitation preserves the upstream leading conclusion", async ({ page }) => {
  const result = successResponse({
    data_quality: { status: "caution", issues: [{ code: "insufficient_scope_rows", severity: "blocking", source_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], affects_selected_target: false, evidence_refs: ["EV5"] }] },
    supporting_evidence: [...successResponse().supporting_evidence, { evidence_ref: "EV5", kind: "data_quality", source_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], target_scope: [], dimension: null, segment: null, baseline_value: null, comparison_value: null, signed_change: null, local_contribution_pct: null, global_contribution_pct: null, quality_code: "insufficient_scope_rows" }],
  });
  await mockApi(page, { rcaResponse: result });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.getByRole("heading", { name: "Leading tested contributor", exact: true })).toBeVisible();
  await expect(page.getByText(/Downstream limitation: this issue does not invalidate/)).toBeVisible();
  await expect(page.locator(".quality-issue.downstream")).toBeVisible();
});

test("target data-quality abstention is rendered as an analytical result", async ({ page }) => {
  await mockApi(page, { rcaResponse: abstentionResponse() });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.getByRole("heading", { name: "No tested path was selected" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data-quality abstention" })).toBeVisible();
  await expect(page.locator(".quality-issue.target")).toContainText("This issue affects the selected target");
  await expect(page.getByRole("heading", { name: "Not ready" })).toBeVisible();
});

test("no-material-driver result remains inconclusive", async ({ page }) => {
  await mockApi(page, { rcaResponse: inconclusiveResponse() });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.getByRole("heading", { name: "Inconclusive investigation" })).toBeVisible();
  await expect(page.getByText("No leading tested contributor met the governed evidence and stopping rules.")).toBeVisible();
  await expect(page.getByText("Add a small number of business-relevant candidate dimensions.")).toBeVisible();
});

test("max-depth result explains the governed limit without implying a user control", async ({ page }) => {
  const result = successResponse({
    conclusion: {
      ...successResponse().conclusion,
      terminal_status: "bounded_by_max_depth",
      caveats: ["maximum_depth_boundary", "robustness_applies_to_upstream_scope_only"],
      recommended_next_action: "increase_investigation_depth",
    },
  });
  await mockApi(page, { rcaResponse: result });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.getByText("Further drill-down is recommended, but this investigation has reached the current server-governed depth limit.")).toBeVisible();
  await expect(page.getByText("Continue the investigation one governed level deeper.")).toHaveCount(0);
  assertSemanticSafety(await page.locator("body").innerText());
});

test("RCA 422 errors map inline and preserve the configured form", async ({ page }) => {
  await mockApi(page, { rcaError: { status: 422, body: { error: { code: "invalid_request", message: "The RCA request is invalid.", request_id: "request-422", fields: [{ field: "baseline_period", code: "value_error" }] } } } });
  await uploadAndConfigure(page);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.locator(".api-error")).toContainText("request-422");
  await expect(page.locator("#baselinePeriod-error")).toContainText("The RCA request is invalid.");
  await expect(page.getByLabel("Baseline period", { exact: true })).toHaveValue("2026-01");
  await expect(page.locator("label.dimension-option.selected")).toHaveCount(3);
});

test("upload and network failures are safe and preserve recoverable state", async ({ page }) => {
  await mockApi(page, { uploadError: "The CSV is damaged or uses an unsupported structure." });
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.locator(".api-error")).toContainText("CSV is damaged");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockApi(page, { abortRca: true });
  await page.reload();
  await uploadAndConfigure(page);
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.locator(".api-error")).toContainText("cannot be reached");
  await expect(page.getByLabel("KPI name")).toHaveValue("Revenue");
  await expect(page.getByLabel("Comparison period", { exact: true })).toHaveValue("2026-02");
  await expect(page.locator("label.dimension-option.selected")).toHaveCount(3);
});

test("workspace is responsive on mobile without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await uploadAndConfigure(page);
  await runInvestigation(page);
  const dimensions = await page.evaluate(() => ({ viewport: window.innerWidth, content: document.documentElement.scrollWidth }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);
  await expect(page.getByRole("heading", { name: "Revenue" })).toBeVisible();
});

test("primary configuration controls support keyboard activation", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await mockApi(page);
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await page.getByLabel("Unit optional").fill("EUR");
  await page.getByLabel("Baseline period", { exact: true }).fill("2026-01");
  await page.getByLabel("Comparison period", { exact: true }).fill("2026-02");
  for (const name of ["Country", "Device", "Customer Type"]) {
    const checkbox = page.locator("label.dimension-option", { hasText: name }).locator("input");
    await checkbox.focus();
    await page.keyboard.press("Space");
    await expect(checkbox).toBeChecked();
  }
  const review = page.getByRole("button", { name: "Review investigation" });
  await review.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Confirm the bounded investigation" })).toBeVisible();
  const start = page.getByRole("button", { name: "Start investigation" });
  await start.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("rca-result")).toBeVisible();
  expect(pageErrors).toEqual([]);
});
