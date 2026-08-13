import { formatPercent, formatScope, formatValue, titleize, QUALITY_LABELS } from "@/lib/rcaPresentation";

function EvidenceCard({ evidence, unit }) {
  return (
    <article className="evidence-card" id={`evidence-${evidence.evidence_ref}`} tabIndex="-1">
      <header><span>{evidence.evidence_ref}</span><strong>{titleize(evidence.kind)}</strong></header>
      {evidence.kind === "data_quality" ? (
        <p>{QUALITY_LABELS[evidence.quality_code] || "A bounded data-quality issue was detected."}</p>
      ) : (
        <dl>
          {evidence.dimension && <div><dt>Test</dt><dd>{titleize(evidence.dimension)} · {evidence.segment}</dd></div>}
          <div><dt>Scope</dt><dd>{formatScope(evidence.target_scope?.length ? evidence.target_scope : evidence.source_scope)}</dd></div>
          {evidence.baseline_value != null && <div><dt>Baseline</dt><dd>{formatValue(evidence.baseline_value, unit)}</dd></div>}
          {evidence.comparison_value != null && <div><dt>Comparison</dt><dd>{formatValue(evidence.comparison_value, unit)}</dd></div>}
          {evidence.signed_change != null && <div><dt>Signed movement</dt><dd>{formatValue(evidence.signed_change, unit, { signed: true })}</dd></div>}
          {evidence.local_contribution_pct != null && <div><dt>Parent share</dt><dd>{formatPercent(evidence.local_contribution_pct)}</dd></div>}
          {evidence.global_contribution_pct != null && <div><dt>Total share</dt><dd>{formatPercent(evidence.global_contribution_pct)}</dd></div>}
        </dl>
      )}
    </article>
  );
}

export default function InvestigationEvidence({ evidence, unit }) {
  return (
    <section className="result-section" aria-labelledby="evidence-title">
      <div className="section-heading-row"><div><p className="eyebrow">Audit trail</p><h2 id="evidence-title">Supporting evidence</h2></div><span className="section-count">{evidence?.length || 0} records</span></div>
      {evidence?.length ? <div className="evidence-grid">{evidence.map((item) => <EvidenceCard key={item.evidence_ref} evidence={item} unit={unit} />)}</div> : <p className="empty-state">No public supporting evidence records were returned.</p>}
    </section>
  );
}
