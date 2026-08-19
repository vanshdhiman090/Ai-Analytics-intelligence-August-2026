import path from "node:path";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const revenueFile = path.join(here, "fixtures", "rca-revenue.csv");

const DATASET_ID = "11111111-1111-4111-8111-111111111111";
const DATASET_B_ID = "33333333-3333-4333-8333-333333333333";
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
        revenue: profileColumn("revenue", "numeric", 7, { numeric_role: "quantity" }),
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

function replacementDatasetResponse() {
  return {
    dataset_id: DATASET_B_ID,
    filename: "replacement-sales.csv",
    size_bytes: 4096,
    profile: {
      row_count: 4,
      column_count: 3,
      duplicate_row_count: 0,
      all_null_columns: [],
      constant_columns: [],
      columns: {
        occurred_at: profileColumn("occurred_at", "datetime", 2, { date_semantics: { status: "CONFIDENT_DATE_FORMAT", min_date: "2026-03-01T00:00:00", max_date: "2026-04-01T00:00:00", missing_months: [] } }),
        sales: profileColumn("sales", "numeric", 4, { numeric_role: "quantity" }),
        region: profileColumn("region", "categorical", 2),
      },
    },
    preview: [],
  };
}

function unusableSchemaDatasetResponse() {
  return {
    dataset_id: DATASET_B_ID,
    filename: "unusable-schema.csv",
    size_bytes: 1024,
    profile: {
      row_count: 3,
      column_count: 3,
      duplicate_row_count: 0,
      all_null_columns: [],
      constant_columns: ["constant_field"],
      columns: {
        event_date: profileColumn("event_date", "text", 3, { date_semantics: { status: "INVALID_DATE_COLUMN", min_date: null, max_date: null, missing_months: [] } }),
        revenue_label: profileColumn("revenue_label", "text", 3),
        constant_field: profileColumn("constant_field", "categorical", 1),
      },
    },
    preview: [],
  };
}

function coffeeShopDatasetResponse() {
  return {
    dataset_id: DATASET_B_ID,
    filename: "coffee-shop.csv",
    size_bytes: 20480,
    profile: {
      row_count: 100,
      column_count: 10,
      duplicate_row_count: 0,
      all_null_columns: [],
      constant_columns: [],
      columns: {
        date: profileColumn("date", "datetime", 30, { date_semantics: { status: "CONFIDENT_DATE_FORMAT", min_date: "2026-01-01T00:00:00", max_date: "2026-01-30T00:00:00", missing_months: [] } }),
        transaction_id: profileColumn("transaction_id", "numeric", 100, { numeric_role: "identifier" }),
        store_id: profileColumn("store_id", "numeric", 5, { numeric_role: "identifier" }),
        product_id: profileColumn("product_id", "numeric", 40, { numeric_role: "identifier" }),
        Hour: profileColumn("Hour", "numeric", 24, { numeric_role: "cyclical" }),
        Month: profileColumn("Month", "numeric", 12, { numeric_role: "cyclical" }),
        "Day of Week": profileColumn("Day of Week", "numeric", 7, { numeric_role: "cyclical" }),
        Rating: profileColumn("Rating", "numeric", 5, { numeric_role: "discrete_scale" }),
        "Total Bill": profileColumn("Total Bill", "numeric", 37, { numeric_role: "quantity" }),
        "Unit Price": profileColumn("Unit Price", "numeric", 23, { numeric_role: "quantity" }),
        Category: profileColumn("Category", "categorical", 4),
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
    leading_contributor: { source_scope: [filter("country", "Germany"), filter("device", "Mobile")], target_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], dimension: "customer_type", segment: "Returning", baseline_value: 26000, comparison_value: 16500, signed_change: -9500, local_contribution_pct: 111.765, global_contribution_pct: 63.333, evidence_strength: "strong", evidence_refs: ["EV4"], prioritization_rationale: "Returning customers in Germany's mobile segment carried a large baseline share, worth testing directly." },
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
  let uploadAttempt = 0;
  let rcaAttempt = 0;
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/datasets" && request.method() === "POST") {
      const currentUploadAttempt = uploadAttempt++;
      const scripted = options.uploadSequence?.[currentUploadAttempt];
      if (scripted?.abort || options.abortUpload) return route.abort();
      if (scripted?.error) return route.fulfill({ status: scripted.error.status, headers: { "X-Request-ID": scripted.error.body.error.request_id }, json: scripted.error.body });
      if (options.uploadError) return route.fulfill({ status: 400, json: { detail: options.uploadError } });
      return route.fulfill({ status: 201, json: scripted?.response || options.datasetResponses?.[currentUploadAttempt] || datasetResponse() });
    }
    if ([`/datasets/${DATASET_ID}`, `/datasets/${DATASET_B_ID}`].includes(url.pathname) && request.method() === "DELETE") return route.fulfill({ status: 204, body: "" });
    if (url.pathname === "/v1/rca/investigations" && request.method() === "POST") {
      payloads.push(request.postDataJSON());
      const currentRcaAttempt = rcaAttempt++;
      const scripted = options.rcaSequence?.[currentRcaAttempt];
      if (scripted?.abort || options.abortRca) return route.abort();
      if (scripted?.delay || options.delay) await new Promise((resolve) => setTimeout(resolve, scripted?.delay || options.delay));
      const error = scripted?.error || options.rcaError;
      if (error) return route.fulfill({ status: error.status, headers: { "X-Request-ID": error.body.error.request_id }, json: error.body });
      return route.fulfill({ status: 200, json: scripted?.response || options.rcaResponse || successResponse() });
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
  const globalPathDescription = page.locator(".global-node .path-main small");
  await expect(globalPathDescription).toHaveText("All supplied records in the requested periods");
  expect(await globalPathDescription.evaluate((element) => getComputedStyle(element).display)).toBe("block");
  await expect(page.getByRole("heading", { name: "Leading tested contributor", exact: true })).toBeVisible();
  await expect(page.locator("label.dimension-option", { hasText: "Constant Field" })).toHaveCount(0);
  // No target-affecting data-quality issue was returned: the early warning banner is a no-op.
  await expect(page.locator(".quality-alert")).toHaveCount(0);
  await expect(page.locator(".leader-metrics dt", { hasText: "Contribution magnitude" })).toBeVisible();
  await expect(page.locator(".path-metrics dt", { hasText: "Contribution magnitude" })).toHaveCount(3);
  await expect(page.getByText("+111.8%", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".decomposition-grid div", { hasText: "Positive offsets" })).toContainText("+");
  await expect(page.getByText("Remaining movement across other segments in this decomposition", { exact: true })).toBeVisible();
  await expect(page.locator(".decomposition-grid dt", { hasText: "Reconciliation tie-out" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Not verified at the selected target" })).toBeVisible();
  await expect(page.locator(".incident-change")).toContainText("-15%");
  await expect(page.locator(".leader-card")).toContainText("Why this was checked");
  await expect(page.locator(".leader-card")).toContainText("written before any results were known");
  await expect(page.locator(".leader-card")).toContainText("Returning customers in Germany's mobile segment carried a large baseline share, worth testing directly.");
  assertSemanticSafety(await page.locator("body").innerText());
  expect(pageErrors).toEqual([]);
});

test("the setup wizard surfaces placeholder-label prevalence next to null prevalence", async ({ page }) => {
  const base = datasetResponse();
  const withPlaceholderColumn = {
    ...base,
    profile: {
      ...base.profile,
      columns: {
        ...base.profile.columns,
        country: profileColumn("country", "categorical", 3, { placeholder_count: 3, placeholder_pct: 30 }),
      },
    },
  };
  await mockApi(page, { datasetResponses: [withPlaceholderColumn] });
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.getByRole("heading", { name: "Define the additive KPI" })).toBeVisible();
  const countryOption = page.locator("label.dimension-option", { hasText: "Country" });
  await expect(countryOption).toContainText("30% placeholder values");
  await expect(countryOption).toContainText("missing-data placeholders");
  const deviceOption = page.locator("label.dimension-option", { hasText: "Device" });
  await expect(deviceOption).not.toContainText("placeholder values");
});

test("prioritization rationale renders nothing when the LLM did not supply it", async ({ page }) => {
  const base = successResponse();
  const result = successResponse({
    leading_contributor: { ...base.leading_contributor, prioritization_rationale: null },
  });
  await mockApi(page, { rcaResponse: result });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.getByRole("heading", { name: "Leading tested contributor", exact: true })).toBeVisible();
  await expect(page.locator(".leader-card")).not.toContainText("Why this was checked");
  await expect(page.locator(".leader-card")).not.toContainText("null");
});

test("segment-reliability data-quality issues surface row counts near the flagged evidence", async ({ page }) => {
  const base = successResponse();
  const result = successResponse({
    conclusion: { ...base.conclusion, caveats: [...base.conclusion.caveats, "insufficient_segment_reliability"] },
    data_quality: { status: "caution", issues: [{ code: "insufficient_segment_sample", severity: "caution", source_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], affects_selected_target: true, evidence_refs: ["EV5"] }] },
    supporting_evidence: [...base.supporting_evidence, { evidence_ref: "EV5", kind: "data_quality", source_scope: [filter("country", "Germany"), filter("device", "Mobile"), filter("customer_type", "Returning")], target_scope: [], dimension: null, segment: null, baseline_value: null, comparison_value: null, signed_change: null, local_contribution_pct: null, global_contribution_pct: null, quality_code: "insufficient_segment_sample", baseline_row_count: 4, comparison_row_count: 40 }],
  });
  await mockApi(page, { rcaResponse: result });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  const evidenceCard = page.locator("#evidence-EV5");
  await expect(evidenceCard).toContainText("too few raw rows");
  await expect(evidenceCard).toContainText("Baseline rows");
  await expect(evidenceCard).toContainText("4");
  await expect(evidenceCard).toContainText("Comparison rows");
  await expect(evidenceCard).toContainText("40");
  await expect(page.locator(".caveat-list")).toContainText("could not be independently verified as reliable");

  // The target-affecting caution is surfaced early, above the conclusion --
  // not only in the full data-quality section further down the page.
  const alert = page.locator(".quality-alert");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("too few raw rows");
  const alertBox = await alert.boundingBox();
  const conclusionBox = await page.locator("#conclusion-title").boundingBox();
  expect(alertBox.y).toBeLessThan(conclusionBox.y);
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
  // A downstream-only issue does not target the selection, so no early banner.
  await expect(page.locator(".quality-alert")).toHaveCount(0);
});

test("target data-quality abstention is rendered as an analytical result", async ({ page }) => {
  await mockApi(page, { rcaResponse: abstentionResponse() });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await expect(page.getByRole("heading", { name: "No tested path was selected" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data-quality abstention" })).toBeVisible();
  await expect(page.locator(".quality-issue.target")).toContainText("This issue affects the selected target");
  await expect(page.getByRole("heading", { name: "Not ready" })).toBeVisible();
  // Blocking severity renders the danger variant of the early banner, also above the conclusion.
  const alert = page.locator(".quality-alert");
  await expect(alert).toHaveClass(/danger/);
  const alertBox = await alert.boundingBox();
  const conclusionBox = await page.locator("#conclusion-title").boundingBox();
  expect(alertBox.y).toBeLessThan(conclusionBox.y);
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

test("upload network and size failures remain retryable and expose correlation IDs", async ({ page }) => {
  await mockApi(page, { abortUpload: true });
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.locator(".api-error")).toContainText("cannot be reached");
  await expect(page.getByRole("heading", { name: "Define the additive KPI" })).toHaveCount(0);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockApi(page, { uploadSequence: [{ error: { status: 413, body: { error: { code: "dataset_too_large", message: "The dataset exceeds the 25 MB upload limit.", request_id: "upload-limit-8", fields: [] } } } }, { response: datasetResponse() }] });
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.locator(".api-error")).toContainText("25 MB upload limit");
  await expect(page.locator(".api-error")).toContainText("upload-limit-8");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.getByRole("heading", { name: "Define the additive KPI" })).toBeVisible();
});

test("an uploaded schema without numeric KPI or safe date candidates is bounded before submission", async ({ page }) => {
  await mockApi(page, { datasetResponses: [unusableSchemaDatasetResponse()] });
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.getByText("This dataset has no usable numeric KPI column.")).toBeVisible();
  await expect(page.getByText("This dataset has no confidently parsed date column.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review investigation" })).toBeDisabled();
  await expect(page.locator("label.dimension-option", { hasText: "Constant Field" })).toHaveCount(0);
});

test("KPI picker offers only additive quantities and dimension picker applies role-specific cautions", async ({ page }) => {
  await mockApi(page, { datasetResponses: [coffeeShopDatasetResponse()] });
  await page.goto("/");
  await page.locator("#dataset-file").setInputFiles(revenueFile);
  await expect(page.getByRole("heading", { name: "Define the additive KPI" })).toBeVisible();

  // Identifiers (transaction_id, store_id, product_id), calendar-position columns
  // (Hour, Month, Day of Week), and the discrete rating scale are all numeric but
  // non-additive, so none of them may appear as a summable KPI candidate.
  const metricOptions = await page.getByLabel("Metric column").locator("option").allTextContents();
  expect(metricOptions).toEqual(["Select a numeric field", "Total Bill", "Unit Price"]);
  await page.getByLabel("Metric column").selectOption("Unit Price");

  // Identifier dimension: existing caution, unchanged wording.
  const storeIdOption = page.locator("label.dimension-option", { hasText: "Store Id" });
  await expect(storeIdOption).toHaveClass(/caution/);
  await expect(storeIdOption.locator("em").first()).toHaveText("High cardinality or identifier-like — select only when analytically meaningful");

  // Cyclical (Hour) and discrete-scale (Rating) dimensions: legitimate segmentation axes, no caution.
  const hourOption = page.locator("label.dimension-option", { hasText: "Hour" });
  await expect(hourOption).not.toHaveClass(/caution/);
  const ratingOption = page.locator("label.dimension-option", { hasText: "Rating" });
  await expect(ratingOption).not.toHaveClass(/caution/);
  await expect(ratingOption.locator("em")).toHaveCount(0);

  // Quantity dimension (Total Bill, left unselected as metric): new, distinct caution.
  const totalBillOption = page.locator("label.dimension-option", { hasText: "Total Bill" });
  await expect(totalBillOption).toHaveClass(/caution/);
  await expect(totalBillOption.locator("em").first()).toHaveText("Continuous business quantity — grouping by exact value can fragment data into near single-row segments");

  // Ordinary categorical dimension: unaffected control case.
  await expect(page.locator("label.dimension-option", { hasText: "Category" })).not.toHaveClass(/caution/);

  // Month is hard-excluded from the dimension list entirely: default time grain is "month",
  // so testing the KPI's movement "by month" against a dimension literally named Month is circular.
  await expect(page.locator("label.dimension-option", { hasText: "Month" })).toHaveCount(0);
  await expect(page.locator("label.dimension-option", { hasText: "Day Of Week" })).toHaveCount(1);
});

for (const failure of [
  { name: "dataset unavailable", status: 409, code: "dataset_unavailable", message: "The requested dataset is unavailable.", requestId: "dataset-gone-5" },
  { name: "unexpected backend failure", status: 500, code: "investigation_failed", message: "The RCA investigation could not be completed.", requestId: "server-failure-6" },
]) {
  test(`RCA ${failure.name} preserves configuration and supports a real retry`, async ({ page }) => {
    const error = { status: failure.status, body: { error: { code: failure.code, message: failure.message, request_id: failure.requestId, fields: [] } } };
    await mockApi(page, { rcaSequence: [{ error }, { response: successResponse() }] });
    await uploadAndConfigure(page);
    await page.getByRole("button", { name: "Start investigation" }).click();
    await expect(page.locator(".api-error")).toContainText(failure.message);
    await expect(page.locator(".api-error")).toContainText(failure.requestId);
    await expect(page.getByTestId("rca-result")).toHaveCount(0);
    await expect(page.getByLabel("KPI name")).toHaveValue("Revenue");
    await expect(page.locator("label.dimension-option.selected")).toHaveCount(3);
    await page.getByRole("button", { name: "Review investigation" }).click();
    await page.getByRole("button", { name: "Start investigation" }).click();
    await expect(page.getByTestId("rca-result")).toBeVisible();
  });
}

test("rapid repeated start actions produce only one in-flight investigation", async ({ page }) => {
  const payloads = await mockApi(page, { delay: 250 });
  await uploadAndConfigure(page);
  await page.getByRole("button", { name: "Start investigation" }).evaluate((button) => {
    button.click();
    button.click();
  });
  await expect(page.getByTestId("rca-result")).toBeVisible();
  expect(payloads).toHaveLength(1);
});

test("successful dataset replacement clears every stale analytical choice and result", async ({ page }) => {
  await mockApi(page, { datasetResponses: [datasetResponse(), replacementDatasetResponse()] });
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await page.getByRole("button", { name: "Revise inputs" }).click();
  await page.locator("#replace-dataset").setInputFiles(revenueFile);

  await expect(page.getByRole("heading", { name: "replacement-sales.csv" })).toBeVisible();
  await expect(page.getByLabel("Metric column")).toHaveValue("sales");
  await expect(page.getByLabel("KPI name")).toHaveValue("Sales");
  await expect(page.getByLabel("Time column")).toHaveValue("occurred_at");
  await expect(page.getByLabel("Baseline period", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Comparison period", { exact: true })).toHaveValue("");
  await expect(page.locator("label.dimension-option.selected")).toHaveCount(0);
  await expect(page.getByTestId("rca-result")).toHaveCount(0);
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

test("professional shell defaults to dark with only RCA shown as active", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByText("AI Analytics Intelligence", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Root Cause Investigation" })).toBeVisible();
  await expect(page.getByText("Active capability", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Switch to light theme" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Forecasting|Anomaly Detection|Scenario Analysis/ })).toHaveCount(0);
});

test("theme switch persists after reload and essential RCA content remains visible in light mode", async ({ page }) => {
  await mockApi(page);
  await uploadAndConfigure(page);
  await runInvestigation(page);
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("heading", { name: "Revenue" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Leading tested contributor" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data quality" })).toBeVisible();

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Switch to dark theme" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Choose one structured dataset" })).toBeVisible();
});

test("result utilities copy a bounded summary and download only public response fields", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (value) => { window.__copiedInvestigationSummary = value; } },
    });
  });
  await mockApi(page);
  await uploadAndConfigure(page);
  await runInvestigation(page);

  await page.getByRole("button", { name: "Copy summary" }).click();
  await expect(page.getByRole("status")).toHaveText("Investigation summary copied.");
  const copied = await page.evaluate(() => window.__copiedInvestigationSummary);
  expect(copied).toContain("Leading tested contributor:");
  expect(copied).toContain("descriptive contribution evidence; not causal proof");
  expect(copied).not.toContain("confirmed root cause");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download public JSON" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe(`rca-investigation-${INVESTIGATION_ID}.json`);
  const downloadedPath = await download.path();
  const payload = JSON.parse(await readFile(downloadedPath, "utf8"));
  expect(Object.keys(payload).sort()).toEqual([
    "api_version",
    "conclusion",
    "data_quality",
    "investigation_id",
    "investigation_path",
    "kpi_movement",
    "leading_contributor",
    "selected_decomposition",
    "supporting_evidence",
  ]);
  expect(JSON.stringify(payload)).not.toMatch(/prompt|filesystem|secret|internal_state/i);
});
