import { formatPercent, formatScope, formatValue, titleize } from "@/lib/rcaPresentation";

function EvidenceLinks({ refs }) {
  if (!refs?.length) return null;
  return <span className="evidence-links">{refs.map((reference) => <a key={reference} href={`#evidence-${reference}`}>{reference}</a>)}</span>;
}

export default function InvestigationPath({ steps, unit }) {
  if (!steps?.length) {
    return (
      <section className="result-section" aria-labelledby="path-title">
        <div className="section-heading-row"><div><p className="eyebrow">Investigation path</p><h2 id="path-title">No tested path was selected</h2></div></div>
        <p className="empty-state">The conclusion below explains why the investigation stopped without selecting a leading segment path.</p>
      </section>
    );
  }

  return (
    <section className="result-section" aria-labelledby="path-title">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Investigation path</p>
          <h2 id="path-title">Tested investigation path</h2>
          <p className="section-copy">Descriptive contribution path — not a causal chain.</p>
        </div>
      </div>
      <ol className="investigation-path">
        <li className="path-node global-node">
          <span className="path-depth">Start</span>
          <div><strong>Global KPI movement</strong><small>All supplied records in the requested periods</small></div>
        </li>
        {steps.map((step) => (
          <li className="path-node" key={`${step.depth}-${step.dimension}-${step.segment}`}>
            <span className="path-depth">Level {step.depth}</span>
            <div className="path-main">
              <p>Tested by {titleize(step.dimension)}</p>
              <h3>{step.segment}</h3>
              <small>{formatScope(step.target_scope)}</small>
            </div>
            <dl className="path-metrics">
              <div><dt>Segment movement</dt><dd>{formatValue(step.segment_movement, unit, { signed: true })}</dd></div>
              <div><dt>Share of parent</dt><dd>{formatPercent(step.local_contribution_pct)}</dd></div>
              <div><dt>Share of total</dt><dd>{formatPercent(step.global_contribution_pct)}</dd></div>
              <div><dt>Evidence strength</dt><dd>{titleize(step.evidence_strength)}</dd></div>
            </dl>
            <EvidenceLinks refs={step.evidence_refs} />
          </li>
        ))}
      </ol>
      <p className="interpretation-note">Contribution shares can exceed 100% when positive offsets counteract part of the decline. Values are shown without clamping.</p>
    </section>
  );
}
