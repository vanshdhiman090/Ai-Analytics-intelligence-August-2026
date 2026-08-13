"""Reader-facing case-study report and course-inspired stakeholder slides."""

from __future__ import annotations

import base64
import html
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.domain.contracts import ActionPackage


def e(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "Not recorded"))


def items(values: Sequence[Any] | None, empty: str = "None recorded") -> str:
    rows = [value for value in (values or []) if value not in (None, "")]
    return "<ul>" + "".join(f"<li>{e(value)}</li>" for value in rows) + "</ul>" if rows else f"<p class='muted'>{e(empty)}</p>"


def records_table(records: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]], empty: str) -> str:
    if not records:
        return f"<p class='muted'>{e(empty)}</p>"
    head = "".join(f"<th>{e(label)}</th>" for _, label in columns)
    body = "".join("<tr>" + "".join(f"<td>{e(row.get(key))}</td>" for key, _ in columns) + "</tr>" for row in records)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def data_uri(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def profile_columns(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    columns = profile.get("columns") or {}
    if isinstance(columns, Mapping):
        return [dict(value, name=value.get("name", name)) for name, value in columns.items()]
    return list(columns)


def case_study_report(state: Mapping[str, Any], package: ActionPackage) -> str:
    brief = state.get("analysis_brief") or {}
    profile = state.get("schema_profile") or {}
    final_summary = state.get("final_summary") or {}
    stakeholders = brief.get("stakeholders") or []
    operations = (state.get("analysis_plan") or {}).get("operations") or []
    findings = state.get("findings") or []
    evidence = state.get("evidence") or []
    quality = state.get("quality_gates") or []
    first_action = package.recommendations[0].action if package.recommendations else "Resolve open questions before acting."
    stakeholder_table = records_table(stakeholders, [("name", "Stakeholder"), ("role", "Role"), ("decision_interest", "Decision interest")], "Stakeholders were not specified.")
    source_table = records_table(state.get("source_register") or [], [("source_id", "ID"), ("filename", "File"), ("format", "Format"), ("rows", "Rows"), ("columns", "Columns"), ("grain", "Observed grain"), ("licence", "Source / licence")], "No source register was recorded.")
    field_table = records_table(profile_columns(profile), [("name", "Field"), ("dtype", "Stored type"), ("semantic_type", "Semantic type"), ("null_count", "Nulls"), ("unique_count", "Unique")], "No field inventory was recorded.")
    cleaning_table = records_table(state.get("cleaning_log") or [], [("log_id", "ID"), ("action", "Action"), ("columns", "Columns"), ("rows_affected", "Affected"), ("before", "Before"), ("after", "After"), ("reason", "Reason")], "No automatic manipulation was required.")
    integrity_table = records_table(state.get("integrity_checks") or [], [("check_id", "ID"), ("check", "Check"), ("status", "Status"), ("detail", "Result"), ("implication", "Analytical implication")], "No integrity check was recorded.")
    operation_table = records_table(operations, [("operation_id", "ID"), ("kind", "Operation"), ("metric_column", "Metric"), ("dimension_column", "Dimension"), ("aggregation", "Aggregate"), ("rationale", "Rationale")], "No approved calculation was recorded.")
    evidence_table = records_table(evidence, [("evidence_id", "ID"), ("title", "Result"), ("kind", "Operation"), ("quality_status", "Quality"), ("method", "Method"), ("population", "Population")], "No evidence was recorded.")
    finding_html = "".join(f"<article class='finding'><b>{e(item.get('finding_id'))}</b><div><h3>{e(item.get('statement'))}</h3><p>{e(item.get('implication'))}</p><small>Evidence: {e(', '.join(item.get('evidence_ids') or []))} · Confidence: {e(item.get('confidence'))}</small></div></article>" for item in findings) or "<p class='muted'>No validated finding was produced.</p>"
    visual_html = []
    evidence_by_id = {item.get("evidence_id"): item for item in evidence}
    for evidence_id, path in (state.get("chart_paths") or {}).items():
        uri = data_uri(path)
        if not uri:
            continue
        source = evidence_by_id.get(evidence_id, {})
        linked = [item for item in findings if evidence_id in (item.get("evidence_ids") or [])]
        statement = linked[0].get("statement") if linked else source.get("title")
        implication = linked[0].get("implication") if linked else "Use this visual to interpret the observed result."
        visual_html.append(f"<article class='visual'><h3>{e(statement)}</h3><p>{e(implication)}</p><img src='{uri}' alt='{e(source.get('title', evidence_id))}'><small>{e(source.get('title', evidence_id))} · {e(source.get('population'))}</small></article>")
    recommendation_html = "".join(f"<article class='action'><b>{e(item.recommendation_id)}</b><div><h3>{e(item.action)}</h3><p>{e(item.rationale)}</p><small>Owner: {e(item.owner_role)} · Timeframe: {e(item.timeframe)} · Supports: {e(', '.join(item.finding_ids))}</small></div></article>" for item in package.recommendations) or "<p class='muted'>No defensible action was generated.</p>"
    gates = records_table(quality, [("gate_id", "ID"), ("name", "Publication check"), ("status", "Status"), ("severity", "Severity"), ("detail", "Result")], "No publication check was recorded.")
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    body = f"""
<section><h2>Executive Summary</h2><ul class='summary'><li><strong>Bottom line.</strong> {e(state.get('analysis_summary'))}</li><li><strong>Decision supported.</strong> {e(brief.get('decision'))}</li><li><strong>Recommended response.</strong> {e(first_action)}</li></ul></section>
<section class='phase'><div>01 · Ask</div><main><h2>Business task and success criteria</h2><aside><strong>Clear business task</strong><p>{e(brief.get('primary_question', state.get('business_question')))}</p></aside><h3>Objective</h3><p>{e(brief.get('objective'))}</p><h3>Stakeholders and audience</h3>{stakeholder_table}<div class='split'><article><h3>Success criteria</h3>{items(brief.get('success_criteria'))}</article><article><h3>Scope</h3><b>In scope</b>{items(brief.get('in_scope'))}<b>Out of scope</b>{items(brief.get('out_of_scope'))}</article></div></main></section>
<section class='phase'><div>02 · Prepare</div><main><h2>Data sources, credibility, and suitability</h2><h3>All data sources used</h3>{source_table}<aside><strong>ROCCC and permission statement</strong><p>{e((state.get('roccc_answers') or {}).get('source_license'))}</p></aside><div class='kpis'><b>{e(profile.get('row_count'))}<small>Input rows</small></b><b>{e(profile.get('column_count'))}<small>Columns</small></b><b>{e(profile.get('duplicate_row_count'))}<small>Exact duplicates</small></b></div><h3>Field inventory</h3>{field_table}</main></section>
<section class='phase'><div>03 · Process</div><main><h2>Cleaning and manipulation record</h2><p><strong>Validation:</strong> {e(state.get('validation_status'))} · Rows before: {e(final_summary.get('rows_before'))} · Rows after: {e(final_summary.get('rows_after'))}</p><h3>Cleaning log</h3>{cleaning_table}<h3>Integrity checks</h3>{integrity_table}<h3>Quality findings</h3>{items([str(item) for item in state.get('quality_findings') or []], 'No material quality finding was recorded.')}</main></section>
<section class='phase'><div>04 · Analyze</div><main><h2>Analysis summary and calculations</h2><p class='lead'>{e(state.get('analysis_summary'))}</p><h3>Approved calculation plan</h3>{operation_table}<h3>Validated findings</h3>{finding_html}<h3>Evidence register</h3>{evidence_table}</main></section>
<section class='phase'><div>05 · Share</div><main><h2>Supporting visualizations and key findings</h2>{''.join(visual_html) if visual_html else '<p class="muted">No suitable visualization was produced.</p>'}</main></section>
<section class='phase'><div>06 · Act</div><main><h2>High-level insights and recommended action</h2><h3>Top high-level insights</h3>{items([item.get('statement') for item in findings])}<h3>Evidence-linked action plan</h3>{recommendation_html}<div class='split'><article><h3>Monitoring plan</h3>{items(package.monitoring_metrics)}</article><article><h3>Further exploration</h3>{items(state.get('additional_deliverables'))}</article></div><h3>Caveats and assumptions</h3>{items(package.limitations)}</main></section>
<section><h2>Release readiness</h2>{gates}</section>"""
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(state.get('business_question'))}</title><style>
:root{{--navy:#173461;--blue:#2866a6;--teal:#087f8c;--orange:#f5a21b;--paper:#fff;--wash:#f4f7fb;--line:#d8e1ed;--ink:#14213d;--muted:#607089}}*{{box-sizing:border-box}}html{{background:#e9eef5}}body{{margin:0;color:var(--ink);font:15px/1.55 Arial,sans-serif}}.page{{max-width:1120px;margin:28px auto;background:var(--paper);box-shadow:0 12px 40px #1734611f}}header{{padding:60px 70px;background:linear-gradient(130deg,#102548,#173d73 60%,#087f8c);color:white}}header h1{{font-size:40px;line-height:1.08;max-width:900px}}header p{{font-size:18px;color:#dbeafe}}header small{{display:block;margin-top:24px}}article,section>main{{min-width:0}}.content{{padding:48px 70px}}section{{margin-bottom:48px}}h2{{font-size:24px;border-bottom:2px solid var(--line);padding-bottom:9px}}h3{{font-size:16px}}.summary{{list-style:none;padding:0}}.summary li{{font-size:17px;padding:13px 0;border-bottom:1px solid var(--line)}}.phase{{display:grid;grid-template-columns:110px 1fr;gap:26px;border-top:1px solid var(--line);padding-top:28px}}.phase>div{{font-weight:800;color:var(--blue);text-transform:uppercase}}aside{{border-left:5px solid var(--teal);background:#ecfeff;padding:14px 18px;margin:16px 0}}.split,.kpis{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.split article{{background:var(--wash);padding:16px}}.kpis{{grid-template-columns:repeat(3,1fr);margin:16px 0}}.kpis b{{font-size:28px;color:white;background:var(--navy);padding:16px;text-align:center}}.kpis small{{display:block;font-size:11px;font-weight:400}}table{{width:100%;border-collapse:collapse;font-size:12px}}th{{background:var(--navy);color:white;text-align:left}}th,td{{padding:9px;border:1px solid var(--line);vertical-align:top}}.finding,.action{{display:grid;grid-template-columns:58px 1fr;gap:15px;padding:16px 0;border-bottom:1px solid var(--line)}}.finding>b,.action>b{{color:var(--blue)}}.visual{{padding:18px 0 28px;border-bottom:1px solid var(--line)}}.visual img{{display:block;max-width:100%;margin:14px auto;border:1px solid var(--line)}}.lead{{font-size:19px}}.muted,small{{color:var(--muted)}}footer{{padding:20px 70px;background:var(--wash);color:var(--muted);font-size:11px}}.print{{position:fixed;right:22px;bottom:22px;border:0;border-radius:99px;background:var(--navy);color:white;padding:12px 17px;font-weight:700}}@media(max-width:760px){{.page{{margin:0}}header,.content,footer{{padding-left:24px;padding-right:24px}}.phase{{grid-template-columns:1fr}}.split,.kpis{{grid-template-columns:1fr}}}}@media print{{html{{background:white}}.page{{margin:0;box-shadow:none;max-width:none}}.print{{display:none}}section,.finding,.action,.visual{{break-inside:avoid}}@page{{size:A4;margin:12mm}}}}
</style></head><body><div class='page'><header><b>CASE STUDY REPORT</b><h1>{e(state.get('business_question'))}</h1><p>Complete Ask–Prepare–Process–Analyze–Share–Act analysis</p><small>Evidence-linked · Generated {e(generated)}</small></header><div class='content'>{body}</div><footer>AI Analytics Workspace · Descriptive findings are not causal proof · Review source permissions before distribution</footer></div><button class='print' onclick='window.print()'>Print / Save PDF</button></body></html>"""


def stakeholder_presentation(state: Mapping[str, Any], package: ActionPackage) -> str:
    brief = state.get("analysis_brief") or {}
    profile = state.get("schema_profile") or {}
    evidence = state.get("evidence") or []
    findings = state.get("findings") or []
    evidence_by_id = {item.get("evidence_id"): item for item in evidence}
    finding_by_evidence = {evidence_id: finding for finding in findings for evidence_id in finding.get("evidence_ids") or []}
    slides = [
        f"<section class='slide cover'><div class='kicker'>CASE STUDY</div><h1>{e(state.get('business_question'))}</h1><div class='rule'></div><p>Stakeholder presentation · Google Data Analytics framework</p></section>",
        f"<section class='slide'><h2>Business Task</h2><div class='quote'>{e(brief.get('primary_question', state.get('business_question')))}</div><div class='three'><article><b>The problem</b><p>{e(brief.get('objective'))}</p></article><article class='accent'><b>The decision</b><p>{e(brief.get('decision'))}</p></article><article><b>Success</b>{items(brief.get('success_criteria'))}</article></div></section>",
        f"<section class='slide'><h2>Data Source & ROCCC</h2><div class='metrics'><b>{e(profile.get('row_count'))}<small>Rows</small></b><b>{e(profile.get('column_count'))}<small>Columns</small></b><b>{e(profile.get('duplicate_row_count'))}<small>Duplicates</small></b></div><div class='two'><article><h3>Source</h3>{records_table(state.get('source_register') or [], [('filename','File'),('format','Format'),('rows','Rows'),('licence','Licence')], 'No source recorded.')}</article><article><h3>ROCCC</h3>{items([f'{key.replace("_", " ").title()}: {value}' for key, value in (state.get('roccc_answers') or {}).items()])}</article></div></section>",
        f"<section class='slide'><h2>Key Findings</h2><div class='finding-grid'>{''.join(f'<article><span>{e(item.get("finding_id"))}</span><h3>{e(item.get("statement"))}</h3><p>{e(item.get("implication"))}</p></article>' for item in findings)}</div></section>",
    ]
    for evidence_id, path in (state.get("chart_paths") or {}).items():
        uri = data_uri(path)
        if not uri:
            continue
        evidence_item = evidence_by_id.get(evidence_id, {})
        finding = finding_by_evidence.get(evidence_id, {})
        slides.append(f"<section class='slide'><h2>{e(finding.get('finding_id', evidence_id))} · {e(evidence_item.get('title'))}</h2><div class='visual'><figure><img src='{uri}' alt='{e(evidence_item.get('title'))}'></figure><aside><div class='insight'><b>Key insight</b><p>{e(finding.get('statement', evidence_item.get('title')))}</p></div><div><b>What this means</b><p>{e(finding.get('implication'))}</p></div></aside></div></section>")
    recommendations = list(package.recommendations)[:3]
    slides.append(f"<section class='slide'><h2>Top Recommendations</h2><div class='recommendations'>{''.join(f'<article><span>{index:02d}</span><h3>{e(item.action)}</h3><p><b>Why:</b> {e(item.rationale)}</p><p><b>Owner:</b> {e(item.owner_role)} · <b>When:</b> {e(item.timeframe)}</p></article>' for index, item in enumerate(recommendations, 1))}</div></section>")
    slides.append(f"<section class='slide conclusion'><div class='kicker'>CONCLUSION</div><h2>Key Takeaways & Next Steps</h2>{items([item.get('statement') for item in findings])}<div class='next'><b>Monitor</b>{items(package.monitoring_metrics)}<b>Explore next</b>{items(state.get('additional_deliverables'))}</div></section>")
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(state.get('business_question'))} · Presentation</title><style>
:root{{--navy:#1c3f72;--navy2:#102f5a;--orange:#f5a21b;--coral:#ef5b48;--paper:#f5f7fb;--ink:#14213d}}*{{box-sizing:border-box}}body{{margin:0;background:#dfe5ee;color:var(--ink);font:18px/1.35 Arial,sans-serif}}.slide{{width:1280px;height:720px;margin:28px auto;padding:54px 64px;background:var(--paper);overflow:hidden;position:relative;box-shadow:0 12px 32px #102f5a22}}h1{{font-size:52px;line-height:1.08;max-width:960px}}h2{{font:700 38px/1.05 Georgia,serif;color:white;background:var(--navy);margin:-54px -64px 34px;padding:24px 64px}}h3{{font-size:21px}}p,li{{font-size:17px}}.cover,.conclusion{{background:var(--navy2);color:white}}.cover h1{{margin-top:110px;color:white}}.kicker{{color:var(--orange);font-weight:800;letter-spacing:.12em}}.rule{{height:5px;width:250px;background:var(--orange);margin:80px 0 16px}}.three,.two,.finding-grid,.recommendations{{display:grid;gap:22px}}.three{{grid-template-columns:repeat(3,1fr)}}.two{{grid-template-columns:1fr 1fr}}.three article,.two article,.finding-grid article,.recommendations article{{background:white;border:1px solid #cad5e4;padding:22px;box-shadow:0 4px 12px #102f5a12}}.three article b,.recommendations span{{display:block;background:var(--navy);color:white;margin:-22px -22px 20px;padding:12px 16px}}.three .accent b{{background:var(--orange)}}.quote{{border:2px solid #3978bd;background:#eaf4fb;padding:24px;text-align:center;font:italic 22px Georgia,serif;margin-bottom:28px}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:22px}}.metrics b{{background:var(--navy);color:white;font-size:38px;padding:18px;text-align:center}}.metrics small{{display:block;font-size:14px;font-weight:400}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:8px;border:1px solid #cad5e4;text-align:left}}th{{background:var(--navy);color:white}}.finding-grid{{grid-template-columns:repeat(3,1fr)}}.finding-grid article span{{color:var(--coral);font-weight:800}}.visual{{display:grid;grid-template-columns:2.2fr .9fr;gap:26px;height:560px}}figure{{margin:0;background:white;border:1px solid #ccd6e4;padding:12px;display:flex;align-items:center}}figure img{{max-width:100%;max-height:520px;margin:auto}}aside{{display:grid;align-content:start;gap:18px}}aside>div{{background:white;border:1px solid #cad5e4;padding:20px}}aside .insight{{background:var(--navy);color:white}}.recommendations{{grid-template-columns:repeat(3,1fr);height:520px}}.recommendations article{{border-left:8px solid var(--orange)}}.conclusion h2{{background:transparent;margin:18px 0 30px;padding:0;font-size:46px}}.conclusion li{{margin:16px 0}}.next{{position:absolute;right:64px;bottom:54px;width:42%;background:#2c5d9b;padding:20px}}.print{{position:fixed;right:20px;bottom:20px;padding:12px 18px;border:0;border-radius:99px;background:var(--orange);font-weight:800}}@media print{{body{{background:white}}.slide{{margin:0;box-shadow:none;break-after:page}}.print{{display:none}}@page{{size:13.333in 7.5in;margin:0}}}}
</style></head><body>{''.join(slides)}<button class='print' onclick='window.print()'>Print / Save PDF</button></body></html>"""
