import { expect, test } from "@playwright/test";


const DATASET_ID = "55555555-5555-4555-8555-555555555555";


function profileColumn(name, semanticType, uniqueCount, extras = {}) {
  return {
    name,
    dtype: "object",
    semantic_type: semanticType,
    null_count: 0,
    null_pct: 0,
    unique_count: uniqueCount,
    sample_values: [],
    ...extras,
  };
}


function demoDatasetResponse() {
  return {
    dataset_id: DATASET_ID,
    filename: "rca-revenue-incident.csv",
    size_bytes: 18432,
    profile: {
      row_count: 320,
      column_count: 7,
      duplicate_row_count: 0,
      all_null_columns: [],
      constant_columns: [],
      columns: {
        date: profileColumn("date", "datetime", 59, {
          date_semantics: {
            status: "CONFIDENT_DATE_FORMAT",
            min_date: "2026-01-01T00:00:00",
            max_date: "2026-02-28T00:00:00",
            missing_months: [],
          },
        }),
        revenue: profileColumn("revenue", "numeric", 8),
        country: profileColumn("country", "categorical", 4),
        device: profileColumn("device", "categorical", 2),
        customer_type: profileColumn("customer_type", "categorical", 2),
        channel: profileColumn("channel", "categorical", 2),
        order_id: profileColumn("order_id", "text", 320),
      },
    },
    preview: [],
  };
}


test("recruiter mode replaces upload with the validated demo and enters configuration", async ({ page }) => {
  const demoRequests = [];
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/v1/demo/datasets/hero" && request.method() === "POST") {
      demoRequests.push(request.url());
      return route.fulfill({ status: 201, json: demoDatasetResponse() });
    }
    return route.fulfill({ status: 404, json: { detail: "Unexpected recruiter-demo request" } });
  });

  await page.goto("/");
  await expect(page.getByRole("button", { name: "Try validated demo" })).toBeVisible();
  await expect(page.getByText("No external data upload is enabled in this public recruiter demo.", { exact: false })).toBeVisible();
  await expect(page.locator("input[type='file']")).toHaveCount(0);

  await page.getByRole("button", { name: "Try validated demo" }).click();
  await expect(page.getByRole("heading", { name: "Define the additive KPI" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "rca-revenue-incident.csv" })).toBeVisible();
  await expect(page.getByText("320", { exact: true })).toBeVisible();
  await expect(page.getByText("Replace dataset", { exact: true })).toHaveCount(0);
  await expect(page.locator("input[type='file']")).toHaveCount(0);
  expect(demoRequests).toHaveLength(1);
});
