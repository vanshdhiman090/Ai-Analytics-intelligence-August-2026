export const CLAIM_LABELS = {
  mathematical_observation: "Mathematical observation",
  leading_tested_contributor: "Leading tested contributor",
  robust_descriptive_explanation: "Robust descriptive explanation",
  competing_explanations: "Competing descriptive explanations",
  data_quality_abstention: "Data-quality abstention",
  inconclusive: "Inconclusive investigation",
};

export const READINESS_LABELS = {
  ready: "Ready for a stronger descriptive explanation",
  ready_with_caveats: "Ready with caveats",
  not_ready: "Not ready",
};

export const READINESS_REASONS = {
  data_quality: "Data quality is not sufficient for this selected target.",
  incomplete_testing: "Required testing was not completed.",
  reconciliation: "The tested decomposition did not reconcile safely.",
  competing_explanations: "Material competing explanations remain.",
  insufficient_evidence: "The available evidence is insufficient.",
  verification_incomplete: "Independent verification was not completed for this target.",
};

export const ROBUSTNESS_LABELS = {
  robust: "Robust descriptive explanation",
  robust_with_caveats: "Robust with caveats",
  weakened: "Weakened by verification",
  competing: "Competing explanations remain",
  not_verified: "Not verified",
  abstained: "Verification abstained",
};

export const CAVEAT_LABELS = {
  material_offsets: "Material positive offsets affect the net movement.",
  leading_segment_remainder: "Other segments still account for material movement in this decomposition.",
  competing_decomposition: "Another tested decomposition provides a material competing explanation.",
  maximum_depth_boundary: "The investigation stopped at the governed maximum depth.",
  downstream_scope_data_quality: "A deeper scope was limited by downstream data quality.",
  nonblocking_data_quality: "A non-blocking data-quality caution remains.",
  insufficient_evidence: "Evidence is insufficient for a stronger descriptive explanation.",
  incomplete_testing: "Required testing is incomplete.",
  reconciliation_failure: "The selected decomposition did not tie out safely.",
  verification_not_completed: "Independent verification was not completed.",
  no_material_driver: "No tested segment contributed enough movement to lead the investigation.",
  robustness_applies_to_upstream_scope_only: "Verification does not apply to the selected deepest target.",
  insufficient_segment_reliability: "The leading segment's own raw data could not be independently verified as reliable.",
};

export const NEXT_ACTION_LABELS = {
  none_required: "No additional analytical test is required for this bounded descriptive conclusion.",
  inspect_competing_explanation: "Inspect the strongest competing explanation.",
  improve_data_quality: "Repair the identified data-quality issue, then rerun the same investigation.",
  collect_more_data: "Collect enough comparable data for the requested periods and scope.",
  expand_candidate_dimensions: "Add a small number of business-relevant candidate dimensions.",
  increase_investigation_depth: "Further drill-down is recommended, but this investigation has reached the current server-governed depth limit.",
  review_large_offsets: "Review the segments creating the largest positive offsets.",
  complete_required_testing: "Complete the required deterministic contribution tests.",
  repair_reconciliation: "Repair the decomposition definition so the arithmetic ties out.",
};

export const QUALITY_LABELS = {
  required_fields_missing: "Required fields are missing",
  invalid_dates: "Date values are invalid or ambiguous",
  requested_period_missing: "A requested period is missing",
  comparison_coverage_incomplete: "Comparison-period coverage is incomplete",
  metric_completeness_failed: "KPI completeness failed",
  insufficient_scope_rows: "The downstream scope has too few rows",
  other_bounded_quality_issue: "A bounded data-quality issue was detected",
  insufficient_segment_sample: "This segment has too few raw rows in one period to trust the measured change",
  segment_structurally_absent: "This segment's rows disappeared or newly appeared between periods — a structural change, not a measured decline",
  segment_baseline_unavailable: "This segment's baseline period has no usable metric values — there is no baseline to compare against",
  segment_label_not_interpretable: "This segment's label is a missing-data placeholder, not a business category — its movement is measured but cannot support a descriptive explanation",
};

export function titleize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatNumber(value, maximumFractionDigits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return "Not established";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits });
}

function currencyFormatter(unit, signed) {
  if (!/^[A-Z]{3}$/.test(unit || "")) return null;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: unit,
      maximumFractionDigits: 2,
      signDisplay: signed ? "always" : "auto",
    });
  } catch {
    return null;
  }
}

export function formatValue(value, unit, { signed = false } = {}) {
  if (value == null || !Number.isFinite(Number(value))) return "Not established";
  const numeric = Number(value);
  const currency = currencyFormatter(unit, signed);
  if (currency) return currency.format(numeric);
  const formatted = numeric.toLocaleString(undefined, {
    maximumFractionDigits: 2,
    signDisplay: signed ? "always" : "auto",
  });
  return unit ? `${formatted} ${unit}` : formatted;
}

export function formatPercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return "Not established";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1, signDisplay: "always" })}%`;
}

export function percentageMovement(baseline, signedChange) {
  const baselineNumber = Number(baseline);
  const changeNumber = Number(signedChange);
  if (!Number.isFinite(baselineNumber) || !Number.isFinite(changeNumber) || baselineNumber === 0) return null;
  return (changeNumber / Math.abs(baselineNumber)) * 100;
}

export function formatScope(scope) {
  if (!Array.isArray(scope) || !scope.length) return "Global";
  return scope.map((item) => `${titleize(item.dimension)}: ${item.segment}`).join(" → ");
}

export function boundedGoal(form) {
  return `Investigate why ${form.kpiName.trim()} changed between ${form.baselinePeriod} and ${form.comparisonPeriod} within the approved dimensions.`;
}

export function fieldLabel(field) {
  return titleize(field?.split(".").at(-1) || "field");
}
