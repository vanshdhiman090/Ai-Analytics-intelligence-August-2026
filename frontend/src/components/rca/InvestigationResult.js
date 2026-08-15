import InvestigationEvidence from "@/components/rca/InvestigationEvidence";
import InvestigationPath from "@/components/rca/InvestigationPath";
import ResultUtilities from "@/components/shared/ResultUtilities";
import {
  CAVEAT_LABELS,
  CLAIM_LABELS,
  NEXT_ACTION_LABELS,
  QUALITY_LABELS,
  READINESS_LABELS,
  READINESS_REASONS,
  ROBUSTNESS_LABELS,
  formatPercent,
  formatScope,
  formatValue,
  percentageMovement,
  titleize,
} from "@/lib/rcaPresentation";

function EvidenceLinks({ refs }) {
  if (!refs?.length) return null;
  return <span className="evidence-links" aria-label="Supporting evidence references">{refs.map((reference) => <a key={reference} href={`#evidence-${reference}`}>{reference}</a>)}</span>;
}

function KpiIncident({ movement }) {
  const percent = percentageMovement(movement.baseline_value, movement.signed_change);
  return (
    <section className="incident-panel" aria-labelledby="incident-title">
      <div>
        <p className="eyebrow">KPI incident</p>
        <h1 id="incident-title">{movement.name}</h1>
        <p>{movement.baseline_period} compared with {movement.comparison_period}</p>
      </div>
      <div className="incident-values">
        <div><span>Baseline</span><strong>{formatValue(movement.baseline_value, movement.unit)}</strong></div>
        <span className="incident-arrow" aria-hidden="true">→</span>
        <div><span>Comparison</span><strong>{formatValue(movement.comparison_value, movement.unit)}</strong></div>
      </div>
      <div className="incident-change">
        <strong>{formatValue(movement.signed_change, movement.unit, { signed: true })}</strong>
        <span>{percent == null ? "Percentage change is not defined" : formatPercent(percent)}</span>
      </div>
      <EvidenceLinks refs={movement.evidence_refs} />
    </section>
  );
}

function ConclusionPanel({ result }) {
  const { conclusion, leading_contributor: leading, kpi_movement: movement } = result;
  return (
    <section className="result-section" aria-labelledby="conclusion-title">
      <div className="section-heading-row"><div><p className="eyebrow">Conclusion</p><h2 id="conclusion-title">{CLAIM_LABELS[conclusion.claim] || titleize(conclusion.claim)}</h2></div><span className={`status-pill claim ${conclusion.claim}`}>{titleize(conclusion.terminal_status)}</span></div>
      {leading ? (
        <div className="leader-card">
          <div className="leader-copy">
            <span>Leading tested contributor</span>
            <h3>{titleize(leading.dimension)} · {leading.segment}</h3>
            <p>{formatScope(leading.target_scope)}</p>
          </div>
          <dl className="leader-metrics">
            <div><dt>Signed movement</dt><dd>{formatValue(leading.signed_change, movement.unit, { signed: true })}</dd></div>
            <div><dt>Share of parent</dt><dd>{formatPercent(leading.local_contribution_pct)}</dd></div>
            <div><dt>Share of total</dt><dd>{formatPercent(leading.global_contribution_pct)}</dd></div>
            <div><dt>Evidence strength</dt><dd>{titleize(leading.evidence_strength)}</dd></div>
          </dl>
          <EvidenceLinks refs={leading.evidence_refs} />
        </div>
      ) : <p className="empty-state">No leading tested contributor met the governed evidence and stopping rules.</p>}
      <p className="interpretation-note">This is a bounded descriptive conclusion based on the tested dimensions. It does not establish causal proof.</p>
      <EvidenceLinks refs={conclusion.evidence_refs} />
    </section>
  );
}

function TargetDecomposition({ decomposition, unit }) {
  if (!decomposition) {
    return <section className="result-section" aria-labelledby="decomposition-title"><p className="eyebrow">Contribution arithmetic</p><h2 id="decomposition-title">No target decomposition selected</h2><p className="empty-state">The investigation stopped before a publishable target decomposition was selected.</p></section>;
  }
  return (
    <section className="result-section" aria-labelledby="decomposition-title">
      <div className="section-heading-row"><div><p className="eyebrow">Contribution arithmetic</p><h2 id="decomposition-title">Target decomposition</h2><p className="section-copy">{formatScope(decomposition.source_scope)} tested by {titleize(decomposition.dimension)}</p></div><span className={`status-pill ${decomposition.reconciles ? "pass" : "warning"}`}>{decomposition.reconciles ? "Ties out" : "Tie-out failed"}</span></div>
      <dl className="decomposition-grid">
        <div><dt>Parent movement</dt><dd>{formatValue(decomposition.parent_movement, unit, { signed: true })}</dd></div>
        <div><dt>Complete tested dimension movement</dt><dd>{formatValue(decomposition.dimension_net_movement, unit, { signed: true })}</dd></div>
        <div><dt>Leading segment movement</dt><dd>{formatValue(decomposition.leading_segment_movement, unit, { signed: true })}</dd></div>
        <div><dt>Remaining movement across other segments in this decomposition</dt><dd>{formatValue(decomposition.remaining_segment_movement, unit, { signed: true })}</dd></div>
        <div className="negative"><dt>Total downward pressure</dt><dd>{formatValue(decomposition.downward_pressure, unit, { signed: true })}</dd></div>
        <div className="positive"><dt>Positive offsets</dt><dd>{formatValue(decomposition.positive_offsets, unit, { signed: true })}</dd></div>
        <div className="tie-out"><dt>Reconciliation tie-out</dt><dd>{formatValue(decomposition.reconciliation_residual, unit, { signed: true })}</dd></div>
      </dl>
      <div className="formula-notes">
        <p><strong>Remaining movement</strong> = parent movement minus leading segment movement.</p>
        <p><strong>Reconciliation tie-out</strong> = parent movement minus the complete tested dimension movement. A reconciled decomposition should normally be near zero.</p>
      </div>
      <EvidenceLinks refs={decomposition.evidence_refs} />
    </section>
  );
}

function StatusSummary({ conclusion }) {
  const readiness = conclusion.readiness || {};
  const robustness = conclusion.robustness || {};
  const robustnessLabel = robustness.applies_to_selected_target ? ROBUSTNESS_LABELS[robustness.status] : "Not verified at the selected target";
  return (
    <div className="status-grid">
      <section className={`status-card readiness ${readiness.status}`} aria-labelledby="readiness-title">
        <p className="eyebrow">Readiness</p>
        <h2 id="readiness-title">{READINESS_LABELS[readiness.status] || titleize(readiness.status)}</h2>
        <p>{readiness.reason ? READINESS_REASONS[readiness.reason] : "The tested evidence supports this bounded descriptive status."}</p>
        <small>Readiness does not establish causal proof.</small>
      </section>
      <section className={`status-card robustness ${robustness.applies_to_selected_target ? robustness.status : "not_verified"}`} aria-labelledby="robustness-title">
        <p className="eyebrow">Robustness</p>
        <h2 id="robustness-title">{robustnessLabel}</h2>
        <p>{robustness.applies_to_selected_target ? "This verification status applies to the selected target, as a descriptive explanation." : "Available verification may apply only to an upstream scope. It is not attached to the deepest selected target."}</p>
        <small>Robustness is not causal certainty.</small>
      </section>
    </div>
  );
}

function Caveats({ caveats }) {
  return (
    <section className="result-section" aria-labelledby="caveats-title">
      <div className="section-heading-row"><div><p className="eyebrow">Interpretation boundaries</p><h2 id="caveats-title">Caveats</h2></div><span className="section-count">{caveats?.length || 0}</span></div>
      {caveats?.length ? <ul className="caveat-list">{caveats.map((code) => <li key={code}><strong>{titleize(code)}</strong><span>{CAVEAT_LABELS[code] || "A bounded interpretation caveat applies."}</span></li>)}</ul> : <p className="empty-state">No controlled caveat codes were returned.</p>}
    </section>
  );
}

function DataQuality({ dataQuality }) {
  const issues = dataQuality?.issues || [];
  return (
    <section className="result-section" aria-labelledby="quality-title">
      <div className="section-heading-row"><div><p className="eyebrow">Evidence safety</p><h2 id="quality-title">Data quality</h2></div><span className={`status-pill ${dataQuality?.status === "pass" ? "pass" : dataQuality?.status === "blocked" ? "danger" : "warning"}`}>{titleize(dataQuality?.status || "unknown")}</span></div>
      {!issues.length ? <p className="quality-pass">No public data-quality issue was detected for the selected investigation.</p> : <div className="quality-list">{issues.map((issue, index) => (
        <article key={`${issue.code}-${index}`} className={`quality-issue ${issue.affects_selected_target ? "target" : "downstream"}`}>
          <div><span className={`status-pill ${issue.severity === "blocking" ? "danger" : "warning"}`}>{titleize(issue.severity)}</span><strong>{QUALITY_LABELS[issue.code] || titleize(issue.code)}</strong></div>
          <p>{issue.affects_selected_target ? "This issue affects the selected target and limits the conclusion at that scope." : "Downstream limitation: this issue does not invalidate the selected upstream conclusion."}</p>
          <small>Scope: {formatScope(issue.source_scope)}</small>
          <EvidenceLinks refs={issue.evidence_refs} />
        </article>
      ))}</div>}
    </section>
  );
}

function NextAction({ action }) {
  return (
    <section className="next-action" aria-labelledby="next-action-title">
      <div><p className="eyebrow">What to do next</p><h2 id="next-action-title">Recommended analytical next action</h2></div>
      <p>{NEXT_ACTION_LABELS[action] || "Review the bounded investigation evidence before choosing another analytical test."}</p>
    </section>
  );
}

export default function InvestigationResult({ result, onRevise, onNew }) {
  return (
    <div className="result-workspace" data-testid="rca-result">
      <div className="result-toolbar">
        <div><p className="eyebrow">Investigation {result.investigation_id}</p><span>API contract {result.api_version}</span></div>
        <div className="result-toolbar-actions">
          <ResultUtilities result={result} />
          <div className="button-row"><button className="button secondary" type="button" onClick={onRevise}>Revise inputs</button><button className="button primary" type="button" onClick={onNew}>New investigation</button></div>
        </div>
      </div>
      <KpiIncident movement={result.kpi_movement} />
      <InvestigationPath steps={result.investigation_path} unit={result.kpi_movement.unit} />
      <ConclusionPanel result={result} />
      <TargetDecomposition decomposition={result.selected_decomposition} unit={result.kpi_movement.unit} />
      <StatusSummary conclusion={result.conclusion} />
      <Caveats caveats={result.conclusion.caveats} />
      <DataQuality dataQuality={result.data_quality} />
      <InvestigationEvidence evidence={result.supporting_evidence} unit={result.kpi_movement.unit} />
      <NextAction action={result.conclusion.recommended_next_action} />
    </div>
  );
}
