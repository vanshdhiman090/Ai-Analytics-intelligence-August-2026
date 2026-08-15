import {
  CLAIM_LABELS,
  NEXT_ACTION_LABELS,
  READINESS_LABELS,
  ROBUSTNESS_LABELS,
  formatPercent,
  formatScope,
  formatValue,
  percentageMovement,
  titleize,
} from "@/lib/rcaPresentation";

const PUBLIC_RESULT_FIELDS = [
  "api_version",
  "investigation_id",
  "kpi_movement",
  "investigation_path",
  "leading_contributor",
  "selected_decomposition",
  "conclusion",
  "data_quality",
  "supporting_evidence",
];

export function publicRcaResult(result) {
  return Object.fromEntries(
    PUBLIC_RESULT_FIELDS
      .filter((field) => Object.prototype.hasOwnProperty.call(result || {}, field))
      .map((field) => [field, result[field]]),
  );
}

export function buildInvestigationSummary(result) {
  const movement = result.kpi_movement;
  const conclusion = result.conclusion || {};
  const leading = result.leading_contributor;
  const percent = percentageMovement(movement.baseline_value, movement.signed_change);
  const path = (result.investigation_path || []).map((step) => step.segment).join(" → ") || "No tested path selected";
  const robustness = conclusion.robustness || {};
  const robustnessLabel = robustness.applies_to_selected_target
    ? ROBUSTNESS_LABELS[robustness.status] || titleize(robustness.status)
    : "Not verified at the selected target";

  return [
    `${movement.name}: ${formatValue(movement.baseline_value, movement.unit)} → ${formatValue(movement.comparison_value, movement.unit)}`,
    `Movement: ${formatValue(movement.signed_change, movement.unit, { signed: true })}${percent == null ? "" : ` (${formatPercent(percent)})`}`,
    `Investigation path: ${path}`,
    leading
      ? `Leading tested contributor: ${titleize(leading.dimension)} · ${leading.segment}; ${formatValue(leading.signed_change, movement.unit, { signed: true })}; ${formatPercent(leading.local_contribution_pct)} of parent; scope ${formatScope(leading.target_scope)}.`
      : "Leading tested contributor: none met the governed evidence and stopping rules.",
    `Conclusion: ${CLAIM_LABELS[conclusion.claim] || titleize(conclusion.claim)}`,
    `Readiness: ${READINESS_LABELS[conclusion.readiness?.status] || titleize(conclusion.readiness?.status)}`,
    `Robustness: ${robustnessLabel}`,
    `Data quality: ${titleize(result.data_quality?.status || "unknown")}`,
    `Recommended next action: ${NEXT_ACTION_LABELS[conclusion.recommended_next_action] || titleize(conclusion.recommended_next_action)}`,
    "Interpretation boundary: descriptive contribution evidence; not causal proof.",
  ].join("\n");
}
