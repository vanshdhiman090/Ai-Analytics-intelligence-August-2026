"""Generate one complete case-study report and one stakeholder presentation."""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.domain.contracts import ActionPackage
from app.services.case_study_outputs import case_study_report, stakeholder_presentation


@dataclass(frozen=True)
class GeneratedDocument:
    artifact_type: str
    title: str
    filename: str
    description: str
    document_type: str


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def _items(values: Sequence[Any] | None, empty: str = "Not specified") -> str:
    rows = values or []
    if not rows:
        return f"<p class='empty'>{_e(empty)}</p>"
    return "<ul>" + "".join(f"<li>{_e(value)}</li>" for value in rows) + "</ul>"


def _badge(value: Any, tone: str = "neutral") -> str:
    return f"<span class='badge {tone}'>{_e(value)}</span>"


def _data_uri(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _shell(title: str, subtitle: str, body: str, document_label: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{_e(title)}</title><style>
:root{{--ink:#14213d;--navy:#173461;--blue:#2563eb;--cyan:#06b6d4;--paper:#fff;--wash:#f4f7fb;--line:#d9e1ec;--muted:#607089;--green:#087f5b;--amber:#a15c00;--red:#b42318}}
*{{box-sizing:border-box}} html{{background:#e9eef5}} body{{margin:0;color:var(--ink);font:15px/1.55 Inter,Segoe UI,Arial,sans-serif}}
.page{{max-width:1120px;margin:28px auto;background:var(--paper);box-shadow:0 12px 40px #1e35551a}}
.hero{{padding:64px 70px 54px;color:white;background:linear-gradient(130deg,#102548 0%,#173d73 58%,#087f8c 100%)}}
.eyebrow{{font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;opacity:.78}} h1{{font-size:40px;line-height:1.08;margin:12px 0 14px;max-width:850px}}
.subtitle{{font-size:18px;max-width:780px;color:#dbeafe}} .meta{{display:flex;gap:10px;flex-wrap:wrap;margin-top:26px}}
.meta span{{border:1px solid #ffffff55;border-radius:99px;padding:6px 11px;font-size:12px}}
main{{padding:46px 70px 68px}} section{{margin:0 0 46px}} h2{{font-size:23px;letter-spacing:-.02em;margin:0 0 18px;padding-bottom:9px;border-bottom:2px solid var(--line)}}
h3{{font-size:16px;margin:0 0 8px}} p{{margin:7px 0}} .lead{{font-size:20px;line-height:1.48;color:#223a5e}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}} .grid.three{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.card{{border:1px solid var(--line);border-radius:12px;padding:18px;background:#fff}} .soft{{background:var(--wash)}}
.kpi{{border-top:4px solid var(--blue)}} .kpi .value{{font-size:28px;font-weight:800;line-height:1.1}} .kpi .label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.07em;margin-top:8px}}
.finding{{display:grid;grid-template-columns:64px 1fr;gap:16px;padding:20px 0;border-bottom:1px solid var(--line)}} .finding:last-child{{border-bottom:0}}
.finding-id{{font-weight:800;color:var(--blue);font-size:17px}} .muted,.empty{{color:var(--muted)}} .small{{font-size:12px}}
.summary-list{{list-style:none;padding:0;margin:0}} .summary-list li{{font-size:17px;line-height:1.55;padding:13px 0 13px 22px;border-bottom:1px solid var(--line);position:relative}}
.summary-list li:before{{content:' ';position:absolute;left:0;top:22px;width:8px;height:8px;border-radius:99px;background:var(--blue)}} .summary-list li:last-child{{border-bottom:0}}
.visual-story{{padding:24px 0 4px;border-bottom:1px solid var(--line)}} .visual-story:last-child{{border-bottom:0}} .visual-story figure{{margin-top:16px}}
.scope-list{{display:grid;gap:10px}} .scope-item{{padding:13px 15px;border-left:3px solid var(--blue);background:var(--wash)}}
.action{{padding:18px;border:1px solid var(--line);border-radius:12px;margin:0 0 12px}} .action-head{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}} .action-meta{{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}}
.badge{{display:inline-block;border-radius:99px;padding:3px 8px;font-size:11px;font-weight:700;background:#edf1f6;color:#43516a}}
.badge.high{{background:#dff7ed;color:#087f5b}} .badge.medium{{background:#fff0d7;color:#8a4b00}} .badge.low{{background:#fee4e2;color:#b42318}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th{{background:var(--navy);color:#fff;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
th,td{{padding:11px 12px;border:1px solid var(--line);vertical-align:top}} tr:nth-child(even) td{{background:#f8fafc}}
ul{{margin:8px 0;padding-left:21px}} li{{margin:5px 0}} figure{{margin:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}}
figure img{{display:block;width:100%}} figcaption{{padding:10px 13px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}}
.phase{{display:grid;grid-template-columns:95px 1fr;gap:22px;padding:24px 0;border-bottom:1px solid var(--line)}} .phase-name{{font-weight:800;color:var(--blue);text-transform:uppercase;letter-spacing:.06em}}
.callout{{border-left:5px solid var(--cyan);background:#ecfeff;padding:15px 18px;border-radius:0 10px 10px 0}}
footer{{padding:22px 70px;color:var(--muted);font-size:11px;background:var(--wash);border-top:1px solid var(--line)}}
.print-button{{position:fixed;right:24px;bottom:24px;border:0;border-radius:99px;background:#14213d;color:white;padding:12px 17px;font-weight:700;box-shadow:0 8px 22px #14213d44;cursor:pointer}}
@media(max-width:760px){{.page{{margin:0}}.hero,main,footer{{padding-left:24px;padding-right:24px}}h1{{font-size:31px}}.grid,.grid.three{{grid-template-columns:1fr}}.phase{{grid-template-columns:1fr}}}}
@media print{{html{{background:white}}.page{{max-width:none;margin:0;box-shadow:none}}.print-button{{display:none}}section,.card,figure,.finding{{break-inside:avoid}}@page{{size:A4;margin:13mm}}.hero{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}main{{padding:28px 20px}}footer{{padding:16px 20px}}}}
</style></head><body><div class='page'><header class='hero'><div class='eyebrow'>{_e(document_label)}</div><h1>{_e(title)}</h1><div class='subtitle'>{_e(subtitle)}</div>
<div class='meta'><span>Google Data Analytics framework</span><span>Evidence-linked</span><span>Generated {_e(generated)}</span></div></header><main>{body}</main>
<footer>AI Analytics Workspace · Ask → Prepare → Process → Analyze → Share → Act · Generated from the validated run state. Descriptive results are not causal proof.</footer></div>
<button class='print-button' onclick='window.print()'>Print / Save PDF</button></body></html>"""


def _brief(state: Mapping[str, Any]) -> Mapping[str, Any]:
    return state.get("analysis_brief") or {}


def _profile(state: Mapping[str, Any]) -> Mapping[str, Any]:
    return state.get("schema_profile") or {}


def _profile_columns(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    columns = profile.get("columns") or {}
    if isinstance(columns, Mapping):
        return [dict(value, name=value.get("name", name)) for name, value in columns.items()]
    return list(columns)


def _display_evidence_title(evidence: Mapping[str, Any]) -> str:
    title = str(evidence.get("title") or "Analysis result")
    match = re.match(r"^(sum|mean|median|min|max|count) of (.+) by (.+)$", title, re.IGNORECASE)
    if match:
        aggregation, metric, dimension = match.groups()
        return f"{metric} by {dimension} ({aggregation.lower()})"
    return title[:1].upper() + title[1:]


def _finding_html(findings: Sequence[Mapping[str, Any]]) -> str:
    if not findings:
        return "<p class='empty'>No validated findings were produced.</p>"
    return "".join(
        f"<article class='finding'><div class='finding-id'>{_e(item.get('finding_id'))}</div><div>"
        f"<h3>{_e(item.get('statement'))}</h3><p>{_e(item.get('implication'))}</p>"
        f"<p class='small muted'>Confidence: {_badge(item.get('confidence', 'unknown'), str(item.get('confidence', 'neutral')))} · "
        f"Evidence: {_e(', '.join(item.get('evidence_ids') or []))}</p>"
        f"{_items(item.get('caveats'), 'No finding-specific caveat recorded')}</div></article>"
        for item in findings
    )


def _chart_html(state: Mapping[str, Any]) -> str:
    figures = []
    evidence_by_id = {item.get("evidence_id"): item for item in state.get("evidence", [])}
    for evidence_id, path in (state.get("chart_paths") or {}).items():
        uri = _data_uri(path)
        if not uri:
            continue
        evidence = evidence_by_id.get(evidence_id, {})
        figures.append(
            f"<figure><img src='{uri}' alt='{_e(evidence.get('title', evidence_id))}'>"
            f"<figcaption>{_e(evidence_id)} · {_e(evidence.get('title', 'Analysis result'))} · "
            f"{_e(evidence.get('population', 'Population not stated'))}</figcaption></figure>"
        )
    return "<div class='grid'>" + "".join(figures) + "</div>" if figures else "<p class='empty'>No chart was suitable for the executed operations.</p>"


def _visual_story_html(state: Mapping[str, Any]) -> str:
    """Pair each visual with the finding and implication it supports."""
    evidence_by_id = {item.get("evidence_id"): item for item in state.get("evidence", [])}
    findings = state.get("findings") or []
    sections = []
    for evidence_id, path in (state.get("chart_paths") or {}).items():
        uri = _data_uri(path)
        if not uri:
            continue
        evidence = evidence_by_id.get(evidence_id, {})
        linked = [item for item in findings if evidence_id in (item.get("evidence_ids") or [])]
        title = _display_evidence_title(evidence)
        headline = linked[0].get("statement") if linked else title
        interpretation = " ".join(str(item.get("implication") or "") for item in linked).strip()
        caveats = list(evidence.get("caveats") or []) + [caveat for item in linked for caveat in (item.get("caveats") or [])]
        caveat_html = _items(caveats) if caveats else ""
        sections.append(
            f"<article class='visual-story'><h2>{_e(headline)}</h2>"
            f"<p>{_e(interpretation or 'Use this visual to evaluate the observed comparison; no causal conclusion is implied.')}</p>"
            f"<figure><img src='{uri}' alt='{_e(title)}'>"
            f"<figcaption><strong>{_e(evidence.get('title', 'Analysis result'))}</strong> · {_e(evidence.get('population', 'Population not stated'))}</figcaption></figure>"
            f"{caveat_html}</article>"
        )
    return "".join(sections) if sections else "<p class='empty'>No chart was suitable for the executed operations.</p>"


def _measurement_scope(state: Mapping[str, Any]) -> str:
    evidence = state.get("evidence") or []
    if not evidence:
        return "<p class='empty'>No measurement scope was recorded.</p>"
    return "<div class='scope-list'>" + "".join(
        f"<div class='scope-item'><strong>{_e(_display_evidence_title(item))}</strong>"
        f"<div class='small muted'>{_e(item.get('method'))} · {_e(item.get('population'))}</div></div>"
        for item in evidence
    ) + "</div>"


def _recommendation_html(package: ActionPackage) -> str:
    if not package.recommendations:
        return "<p class='empty'>No defensible action was generated from the available evidence.</p>"
    cards = []
    for item in package.recommendations:
        support = ", ".join(item.finding_ids)
        cards.append(
            f"<article class='action'><div class='action-head'><div><span class='finding-id'>{_e(item.recommendation_id)}</span>"
            f"<h3>{_e(item.action)}</h3></div>{_badge(item.expected_impact, item.expected_impact)}</div>"
            f"<p>{_e(item.rationale)}</p><div class='action-meta'>{_badge(f'Owner: {item.owner_role}')}"
            f"{_badge(f'Timeframe: {item.timeframe}')}{_badge(f'Effort: {item.effort}')}{_badge(f'Support: {support}')}</div></article>"
        )
    return "".join(cards)


def _unvisualized_findings_html(state: Mapping[str, Any]) -> str:
    charted_ids = set((state.get("chart_paths") or {}).keys())
    findings = [
        item
        for item in (state.get("findings") or [])
        if not charted_ids.intersection(item.get("evidence_ids") or [])
    ]
    if not findings:
        return ""
    return f"<section><h2>Additional findings</h2>{_finding_html(findings)}</section>"


def executive_report(state: Mapping[str, Any], package: ActionPackage) -> str:
    brief = _brief(state)
    profile = _profile(state)
    final_summary = state.get("final_summary") or {}
    rows_before = final_summary.get("rows_before", profile.get("row_count", "—"))
    rows_after = final_summary.get("rows_after", profile.get("row_count", "—"))
    duplicates = profile.get("duplicate_row_count", "—")
    columns = profile.get("column_count", len(profile.get("columns", [])) or "—")
    first_action = package.recommendations[0].action if package.recommendations else "Monitor the stated metrics and resolve open questions before acting."
    body = f"""
<section><h2>Executive Summary</h2><ul class='summary-list'>
<li><strong>Bottom line.</strong> {_e(state.get('analysis_summary', 'No summary was produced.'))}</li>
<li><strong>Decision supported.</strong> {_e(brief.get('decision', 'The decision owner was not specified.'))}</li>
<li><strong>Recommended response.</strong> {_e(first_action)}</li></ul></section>
<section><h2>What was measured</h2>{_measurement_scope(state)}
<p class='small muted'>Input rows: {_e(rows_before)} · Final rows: {_e(rows_after)} · These are data-volume indicators, not business KPIs.</p></section>
<section>{_visual_story_html(state)}</section>
{_unvisualized_findings_html(state)}
<section><h2>Recommended next steps</h2>{_recommendation_html(package)}</section>
<section><h2>Monitoring plan</h2>{_items(package.monitoring_metrics, 'No defensible monitoring metric could be specified from the supplied context.')}</section>
<section><h2>Further questions</h2>{_items(state.get('additional_deliverables'), 'No decision-relevant open question was recorded.')}</section>
<section><h2>Caveats and assumptions</h2>{_items(package.limitations)}</section>"""
    return _shell(
        str(state.get("business_question", "Analytics decision report")),
        "A concise, evidence-backed answer for decision-makers",
        body,
        "Executive decision report",
    )


def _evidence_table(evidence: Sequence[Mapping[str, Any]]) -> str:
    if not evidence:
        return "<p class='empty'>No evidence records were produced.</p>"
    rows = "".join(
        f"<tr><td><strong>{_e(item.get('evidence_id'))}</strong></td><td>{_e(item.get('title'))}</td>"
        f"<td>{_e(item.get('kind'))}</td><td>{_e(item.get('method'))}</td><td>{_e(item.get('population'))} · Quality: {_e(item.get('quality_status', 'ready'))}</td>"
        f"<td>{_e('; '.join(item.get('caveats') or []))}</td></tr>"
        for item in evidence
    )
    return f"<table><thead><tr><th>ID</th><th>Result</th><th>Operation</th><th>Method</th><th>Population</th><th>Caveat</th></tr></thead><tbody>{rows}</tbody></table>"


def analysis_journal(state: Mapping[str, Any], package: ActionPackage) -> str:
    brief = _brief(state)
    profile = _profile(state)
    stakeholders = brief.get("stakeholders") or []
    stakeholder_rows = "".join(
        f"<tr><td>{_e(s.get('name'))}</td><td>{_e(s.get('role'))}</td><td>{_e(s.get('decision_interest'))}</td></tr>"
        for s in stakeholders
    ) or "<tr><td colspan='3'>Not specified</td></tr>"
    column_rows = "".join(
        f"<tr><td>{_e(c.get('name'))}</td><td>{_e(c.get('dtype'))}</td><td>{_e(c.get('null_count', c.get('nulls')))}</td>"
        f"<td>{_e(c.get('unique_count', c.get('unique')))}</td></tr>" for c in _profile_columns(profile)
    ) or "<tr><td colspan='4'>Column-level inventory was not available.</td></tr>"
    operations = (state.get("analysis_plan") or {}).get("operations", [])
    operation_rows = "".join(
        f"<tr><td>{_e(op.get('operation_id'))}</td><td>{_e(op.get('kind'))}</td><td>{_e(op.get('aggregation'))}</td>"
        f"<td>{_e(op.get('dimension_column'))}</td><td>{_e(op.get('metric_column'))}</td><td>{_e(op.get('rationale'))}</td></tr>"
        for op in operations
    ) or "<tr><td colspan='6'>No operation plan was recorded.</td></tr>"
    quality = state.get("quality_findings") or []
    body = f"""
<section><h2>Run record</h2><div class='grid'><div class='card'><h3>Primary question</h3><p>{_e(state.get('business_question'))}</p></div>
<div class='card'><h3>Objective</h3><p>{_e(brief.get('objective'))}</p></div></div></section>
<section class='phase'><div class='phase-name'>01 · Ask</div><div><h2>Business framing</h2><h3>Decision</h3><p>{_e(brief.get('decision'))}</p>
<h3>Stakeholders</h3><table><thead><tr><th>Name</th><th>Role</th><th>Decision interest</th></tr></thead><tbody>{stakeholder_rows}</tbody></table>
<div class='grid'><div><h3>Success criteria</h3>{_items(brief.get('success_criteria'))}</div><div><h3>Required human context</h3>{_items(brief.get('required_context'))}</div></div>
<h3>Scope boundary</h3><div class='grid'><div class='card soft'><strong>In scope</strong>{_items(brief.get('in_scope'))}</div><div class='card soft'><strong>Out of scope</strong>{_items(brief.get('out_of_scope'))}</div></div></div></section>
<section class='phase'><div class='phase-name'>02 · Prepare</div><div><h2>Source and data readiness</h2><div class='callout'><strong>ROCCC / source response</strong><p>{_e((state.get('roccc_answers') or {}).get('source_license', 'Not supplied'))}</p></div>
<div class='grid three'><div class='card kpi'><div class='value'>{_e(profile.get('row_count'))}</div><div class='label'>Rows</div></div><div class='card kpi'><div class='value'>{_e(profile.get('column_count'))}</div><div class='label'>Columns</div></div><div class='card kpi'><div class='value'>{_e(profile.get('duplicate_row_count'))}</div><div class='label'>Duplicates</div></div></div>
<h3>Data inventory</h3><table><thead><tr><th>Column</th><th>Type</th><th>Nulls</th><th>Unique</th></tr></thead><tbody>{column_rows}</tbody></table></div></section>
<section class='phase'><div class='phase-name'>03 · Process</div><div><h2>Cleaning and quality record</h2><h3>Transformations</h3>{_items((state.get('cleaning_checklist') or {}).get('transformations'))}
<h3>Quality findings</h3>{_items([str(item) for item in quality], 'No quality finding was recorded.')}
<p class='small muted'>Rows before: {_e((state.get('final_summary') or {}).get('rows_before'))} · Rows after: {_e((state.get('final_summary') or {}).get('rows_after'))}</p></div></section>
<section class='phase'><div class='phase-name'>04 · Analyze</div><div><h2>Controlled analysis plan</h2><p>{_e((state.get('analysis_plan') or {}).get('objective'))}</p>
<table><thead><tr><th>ID</th><th>Kind</th><th>Aggregate</th><th>Dimension</th><th>Metric</th><th>Rationale</th></tr></thead><tbody>{operation_rows}</tbody></table>
<h3>Validated findings</h3>{_finding_html(state.get('findings', []))}</div></section>
<section class='phase'><div class='phase-name'>05 · Share</div><div><h2>Visual evidence</h2>{_chart_html(state)}</div></section>
<section class='phase'><div class='phase-name'>06 · Act</div><div><h2>Decision follow-through</h2>{_items([f"{r.recommendation_id}: {r.action} — owner: {r.owner_role}; timeframe: {r.timeframe}" for r in package.recommendations])}
<h3>Monitoring metrics</h3>{_items(package.monitoring_metrics)}</div></section>
<section><h2>Evidence and limitations appendix</h2>{_evidence_table(state.get('evidence', []))}<h3>Run limitations</h3>{_items(package.limitations)}</section>"""
    return _shell(
        str(state.get("business_question", "Analysis journal")),
        "A reproducible record of decisions, data handling, calculations, evidence, and caveats",
        body,
        "Analysis journal",
    )


def analysis_brief(state: Mapping[str, Any]) -> str:
    brief = _brief(state)
    stakeholders = brief.get("stakeholders") or []
    stakeholder_rows = "".join(
        f"<tr><td>{_e(s.get('name'))}</td><td>{_e(s.get('role'))}</td><td>{_e(s.get('decision_interest'))}</td></tr>" for s in stakeholders
    ) or "<tr><td colspan='3'>Not specified</td></tr>"
    body = f"""
<section><h2>Purpose</h2><p class='lead'>{_e(brief.get('objective', state.get('business_question')))}</p>
<div class='callout'><strong>Decision this work supports</strong><p>{_e(brief.get('decision'))}</p></div></section>
<section><h2>Primary analytical question</h2><div class='card soft'><h3>{_e(brief.get('primary_question', state.get('business_question')))}</h3></div></section>
<section><h2>Stakeholders and intended use</h2><table><thead><tr><th>Stakeholder</th><th>Role</th><th>Decision interest</th></tr></thead><tbody>{stakeholder_rows}</tbody></table></section>
<section><h2>Scope and boundaries</h2><div class='grid'><div class='card'><h3>In scope</h3>{_items(brief.get('in_scope'))}</div><div class='card'><h3>Out of scope</h3>{_items(brief.get('out_of_scope'))}</div></div></section>
<section><h2>Success criteria</h2>{_items(brief.get('success_criteria'))}</section>
<section><h2>Assumptions, constraints, and dependencies</h2><div class='grid three'><div class='card soft'><h3>Assumptions</h3>{_items(brief.get('assumptions'))}</div>
<div class='card soft'><h3>Constraints</h3>{_items(brief.get('constraints'))}</div><div class='card soft'><h3>Required context</h3>{_items(brief.get('required_context'))}</div></div></section>
<section><h2>Delivery framework</h2><table><thead><tr><th>Phase</th><th>Purpose</th><th>Quality gate</th></tr></thead><tbody>
<tr><td>Ask</td><td>Confirm the business decision and boundaries</td><td>Human-approved question</td></tr><tr><td>Prepare</td><td>Profile provenance, structure, and suitability</td><td>Source and ROCCC checkpoint</td></tr>
<tr><td>Process</td><td>Apply conservative, logged transformations</td><td>Before/after reconciliation</td></tr><tr><td>Analyze</td><td>Execute allow-listed calculations</td><td>Every claim cites evidence</td></tr>
<tr><td>Share</td><td>Communicate material results visually</td><td>Charts derive from validated evidence</td></tr><tr><td>Act</td><td>Assign evidence-linked next steps</td><td>Owner, timeframe, limitations</td></tr></tbody></table></section>"""
    return _shell(
        str(brief.get("objective", state.get("business_question", "Analysis brief"))),
        "Scope, decision context, success criteria, boundaries, and delivery controls",
        body,
        "Professional analysis brief",
    )


def _records_table(records: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]], empty: str) -> str:
    if not records:
        return f"<p class='empty'>{_e(empty)}</p>"
    header = "".join(f"<th>{_e(label)}</th>" for _, label in columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{_e(item.get(key))}</td>" for key, _ in columns) + "</tr>"
        for item in records
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>"


def technical_appendix(state: Mapping[str, Any]) -> str:
    """Detailed reproducibility companion kept separate from the decision report."""
    profile = _profile(state)
    operations = (state.get("analysis_plan") or {}).get("operations", [])
    body = f"""
<section><h2>Technical scope</h2><p class='lead'>This appendix records source provenance, field structure, transformations, integrity checks, executed calculations, populations, caveats, and publication gates.</p>
<div class='callout'><strong>Reproducibility boundary</strong><p>Only the uploaded file, approved analysis plan, controlled calculation engine, and evidence-linked outputs are represented. External business facts remain human-supplied context.</p></div></section>
<section><h2>Source register</h2>{_records_table(state.get('source_register') or [], [('filename', 'File'), ('format', 'Format'), ('rows', 'Rows'), ('columns', 'Columns'), ('grain', 'Observed grain'), ('licence', 'Source / licence')], 'No structured source register was recorded.')}</section>
<section><h2>Field dictionary</h2>{_records_table(_profile_columns(profile), [('name', 'Field'), ('dtype', 'Stored type'), ('semantic_type', 'Semantic type'), ('null_count', 'Nulls'), ('unique_count', 'Unique'), ('min', 'Minimum'), ('max', 'Maximum')], 'No field-level profile was available.')}</section>
<section><h2>Cleaning log</h2>{_records_table(state.get('cleaning_log') or [], [('log_id', 'ID'), ('action', 'Action'), ('columns', 'Columns'), ('rows_affected', 'Rows affected'), ('before', 'Before'), ('after', 'After'), ('reason', 'Reason')], 'No automatic transformation was required.')}</section>
<section><h2>Integrity checks</h2>{_records_table(state.get('integrity_checks') or [], [('check_id', 'ID'), ('check', 'Check'), ('status', 'Status'), ('detail', 'Result'), ('implication', 'Analytical implication')], 'No integrity check was recorded.')}</section>
<section><h2>Approved calculation plan</h2>{_records_table(operations, [('operation_id', 'ID'), ('kind', 'Operation'), ('metric_column', 'Metric'), ('dimension_column', 'Dimension'), ('time_column', 'Time field'), ('aggregation', 'Aggregate'), ('rationale', 'Rationale')], 'No approved calculation plan was recorded.')}</section>
<section><h2>Evidence register</h2>{_evidence_table(state.get('evidence', []))}</section>
<section><h2>Publication quality gates</h2>{_records_table(state.get('quality_gates') or [], [('gate_id', 'ID'), ('name', 'Gate'), ('status', 'Status'), ('severity', 'Severity'), ('detail', 'Result')], 'No publication gate result was recorded.')}</section>
<section><h2>Known limitations and unresolved questions</h2><div class='grid'><div class='card soft'><h3>Limitations</h3>{_items(state.get('limitations'))}</div><div class='card soft'><h3>Unresolved</h3>{_items(state.get('additional_deliverables'), 'None recorded.')}</div></div></section>
"""
    return _shell(
        str(state.get("business_question", "Technical appendix")),
        "Reproducible methods, data-quality controls, calculations, and publication checks",
        body,
        "Technical appendix",
    )


def write_deliverables(state: Mapping[str, Any], package: ActionPackage, artifact_dir: Path) -> list[GeneratedDocument]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    documents = [
        (GeneratedDocument("report", "Executive decision report", "report.html", "Decision-ready summary with findings, visuals, actions, and limitations", "executive_report"), executive_report(state, package)),
        (GeneratedDocument("documentation", "Analysis journal", "journal.html", "Reproducible Ask–Prepare–Process–Analyze–Share–Act audit record", "analysis_journal"), analysis_journal(state, package)),
        # Keep managed filenames short: the project may live inside a deeply
        # nested OneDrive path and Windows still rejects paths beyond MAX_PATH.
        (GeneratedDocument("documentation", "Technical appendix", "appendix.html", "Source register, field dictionary, cleaning log, integrity checks, methods, and quality gates", "technical_appendix"), technical_appendix(state)),
        (GeneratedDocument("documentation", "Analysis brief", "brief.html", "Business scope, stakeholders, boundaries, and success criteria", "analysis_brief"), analysis_brief(state)),
    ]
    # Google asks for one complete case-study report. The editable native
    # PowerPoint and reproducibility bundle are generated by the package node,
    # not counted as extra report documents.
    documents = [
        (
            GeneratedDocument(
                "report",
                "Case Study Report",
                # Keep runtime filenames short. The project can live inside a
                # deeply nested OneDrive directory where Windows still applies
                # the legacy 260-character path limit.
                "report.html",
                "One editable Google-style report containing the complete six-phase case study",
                "case_study_report",
            ),
            case_study_report(state, package),
        ),
    ]
    for metadata, content in documents:
        (artifact_dir / metadata.filename).write_text(content, encoding="utf-8")
    return [metadata for metadata, _ in documents]
