import fs from "node:fs/promises";
import { pathToFileURL } from "node:url";

const [inputPath, outputPath, artifactToolEntry] = process.argv.slice(2);
if (!inputPath || !outputPath || !artifactToolEntry) {
  throw new Error("Usage: presentation_deck.mjs <input.json> <output.pptx> <artifact_tool.mjs>");
}

const { Presentation, PresentationFile } = await import(pathToFileURL(artifactToolEntry).href);
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

const W = 1280;
const H = 720;
const NAVY = "#081426";
const NAVY_2 = "#10233D";
const INK = "#122033";
const MUTED = "#5B6878";
const PAPER = "#F7F4EE";
const WHITE = "#FFFFFF";
const ORANGE = "#F28C28";
const TEAL = "#23A6A6";
const RULE = "#D8D4CC";

const deck = Presentation.create({ slideSize: { width: W, height: H } });
deck.theme.colorScheme = {
  name: "Analytics Case Study",
  themeColors: {
    accent1: ORANGE,
    accent2: TEAL,
    accent3: "#5375A6",
    accent4: "#C84F44",
    accent5: "#8A6FB0",
    accent6: "#6E8B58",
    bg1: WHITE,
    bg2: PAPER,
    tx1: INK,
    tx2: MUTED,
    dk1: "#000000",
    dk2: NAVY,
    lt1: WHITE,
    lt2: "#E7E2D8",
    hlink: TEAL,
    folHlink: "#8A6FB0",
  },
};

function clean(value, fallback = "Not recorded") {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text || fallback;
}

function truncate(value, max) {
  const text = clean(value, "");
  return text.length <= max ? text : `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

function firstSentence(value, max = 170) {
  const text = clean(value, "");
  const match = text.match(/^.*?[.!?](?:\s|$)/);
  return truncate(match ? match[0].trim() : text, max);
}

function addText(slide, name, text, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = clean(text, "");
  shape.text.style = {
    fontSize: style.fontSize ?? 20,
    bold: style.bold ?? false,
    color: style.color ?? INK,
    alignment: style.alignment ?? "left",
  };
  return shape;
}

function addRule(slide, left, top, width, color = ORANGE, height = 5) {
  return slide.shapes.add({
    geometry: "rect",
    name: `rule-${left}-${top}`,
    position: { left, top, width, height },
    fill: color,
    line: { style: "solid", fill: color, width: 0 },
  });
}

function addFooter(slide, number, label, dark = false) {
  const color = dark ? "#AFC0D6" : MUTED;
  addText(slide, `footer-label-${number}`, label.toUpperCase(), { left: 72, top: 675, width: 500, height: 22 }, { fontSize: 12, bold: true, color });
  addText(slide, `footer-number-${number}`, String(number).padStart(2, "0"), { left: 1160, top: 675, width: 48, height: 22 }, { fontSize: 12, bold: true, color, alignment: "right" });
}

function addLightHeader(slide, title, eyebrow, number) {
  slide.background.fill = PAPER;
  addText(slide, `eyebrow-${number}`, eyebrow.toUpperCase(), { left: 72, top: 48, width: 500, height: 24 }, { fontSize: 13, bold: true, color: TEAL });
  addText(slide, `title-${number}`, truncate(title, 56), { left: 72, top: 82, width: 1136, height: 58 }, { fontSize: 35, bold: true, color: NAVY });
  addRule(slide, 72, 148, 92, ORANGE, 5);
  addFooter(slide, number, eyebrow, false);
}

function addNotes(slide, extra = "") {
  const source = clean(data.original_filename, "Uploaded dataset");
  slide.speakerNotes.textFrame.setText(`[Sources]\n- Uploaded dataset: ${source}\n- Agent-validated evidence and case-study state for session ${clean(data.session_id, "unknown")}\n[/Sources]${extra ? `\n\n${extra}` : ""}`);
}

function bulletList(slide, items, { left, top, width, fontSize = 20, color = INK, gap = 64, maxItems = 5, maxChars = 145 }) {
  items.slice(0, maxItems).forEach((item, index) => {
    addText(slide, `bullet-mark-${left}-${top}-${index}`, "•", { left, top: top + index * gap, width: 24, height: 30 }, { fontSize: fontSize + 2, bold: true, color: ORANGE });
    addText(slide, `bullet-copy-${left}-${top}-${index}`, truncate(item, maxChars), { left: left + 32, top: top + index * gap, width: width - 32, height: gap - 6 }, { fontSize, color });
  });
}

function evidenceFinding(evidenceId) {
  return (data.findings || []).find((finding) => (finding.evidence_ids || []).includes(evidenceId));
}

function evidenceSeries(evidence) {
  const rows = Array.isArray(evidence.rows) ? evidence.rows.slice(0, 12) : [];
  if (!rows.length) return null;
  if (evidence.kind === "statistical_comparison") {
    const row = rows[0];
    return { categories: [clean(row.baseline_group, "Baseline"), clean(row.comparison_group, "Comparison")], values: [Number(row.baseline_mean), Number(row.comparison_mean)], categoryKey: "group", valueKey: "mean" };
  }
  const columns = Object.keys(rows[0]);
  const preferredValue = evidence.kind === "kpi_ratio" ? "ratio" : evidence.kind === "segment_change" ? "absolute_change" : "value";
  const valueKey = columns.includes(preferredValue) ? preferredValue : columns.find((key) => rows.some((row) => Number.isFinite(Number(row[key]))));
  const categoryKey = columns.find((key) => key !== valueKey);
  if (!valueKey || !categoryKey) return null;
  const categories = rows.map((row) => {
    if (evidence.kind === "distribution" && categoryKey.toLowerCase().includes("quantile")) {
      return `${Math.round(Number(row[categoryKey]) * 100)}%`;
    }
    return clean(row[categoryKey], "Unknown");
  });
  const values = rows.map((row) => Number(row[valueKey])).filter(Number.isFinite);
  if (values.length !== categories.length) return null;
  return { categories, values, categoryKey, valueKey };
}

function evidenceHeadline(evidence, series, finding) {
  if (evidence.kind === "grouped_aggregate" && series.categories.length) {
    const metric = clean(evidence.title, "observed value").replace(/^(sum|mean|median|count|min|max)\s+of\s+/i, "").replace(/\s+by\s+.+$/i, "");
    return `${series.categories[0]} leads ${metric}`;
  }
  if (["trend", "period_comparison"].includes(evidence.kind)) return clean(evidence.title, "Trend over time");
  if (evidence.kind === "distribution") return clean(evidence.title, "Observed distribution");
  if (["kpi_ratio", "statistical_comparison", "segment_change"].includes(evidence.kind)) return clean(evidence.title, "Advanced analytical result");
  return finding?.statement || evidence.title;
}

function evidenceFallbackMeaning(evidence) {
  if (["trend", "period_comparison"].includes(evidence.kind)) return "The observed series changes across periods; interpret direction alongside data coverage and missing dates.";
  if (evidence.kind === "distribution") return "Values span a wide range. Review concentration, outliers, and context before acting.";
  if (evidence.kind === "correlation") return "The variables move together in the sample, but the relationship does not establish causation.";
  if (evidence.kind === "statistical_comparison") return "The observed group difference includes an effect size and a deterministic permutation test; it does not establish causality.";
  if (evidence.kind === "segment_change") return "Segment contributions reconcile to the total observed change; verify that the latest period is complete.";
  if (evidence.kind === "kpi_ratio") return "The KPI uses summed numerator and denominator values so the denominator remains explicit and auditable.";
  return firstSentence(data.analysis_summary);
}

function shortLimitation(value) {
  let text = clean(value, "");
  text = text.replace(/^The analysis is constrained by the current findings which only cover /i, "Current evidence covers only ");
  text = text.replace(/^The findings lack causal information regarding /i, "Causal evidence is missing for ");
  text = text.replace(/^Risk assessment was not possible due to a lack of available data on /i, "Risk assessment needs additional data on ");
  if (text.includes(",")) text = `${text.split(",")[0].trim()}.`;
  return truncate(text, 118);
}

// 1. Minimal title slide.
{
  const slide = deck.slides.add();
  slide.background.fill = NAVY;
  addRule(slide, 72, 64, 112, ORANGE, 8);
  addText(slide, "cover-kicker", "STAKEHOLDER PRESENTATION", { left: 72, top: 104, width: 500, height: 28 }, { fontSize: 14, bold: true, color: "#AFC0D6" });
  addText(slide, "cover-title", "Case Study Analysis", { left: 72, top: 206, width: 920, height: 78 }, { fontSize: 54, bold: true, color: WHITE });
  addText(slide, "cover-question", truncate(data.business_question, 180), { left: 72, top: 310, width: 1000, height: 132 }, { fontSize: 26, color: "#DCE5F0" });
  addText(slide, "cover-method", "Ask  •  Prepare  •  Process  •  Analyze  •  Share  •  Act", { left: 72, top: 565, width: 920, height: 34 }, { fontSize: 18, bold: true, color: TEAL });
  addFooter(slide, 1, "Case study", true);
  addNotes(slide);
}

// 2. Business task.
{
  const slide = deck.slides.add();
  addLightHeader(slide, "The decision starts with one clear business question", "Business task", 2);
  addText(slide, "task-question", truncate(data.business_question, 220), { left: 72, top: 205, width: 740, height: 150 }, { fontSize: 29, bold: true, color: NAVY });
  addRule(slide, 862, 205, 5, TEAL, 360);
  addText(slide, "task-objective-label", "OBJECTIVE", { left: 900, top: 210, width: 280, height: 28 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, "task-objective", truncate(data.analysis_brief?.objective, 180), { left: 900, top: 252, width: 300, height: 138 }, { fontSize: 21, color: INK });
  addText(slide, "task-decision-label", "DECISION SUPPORTED", { left: 900, top: 420, width: 280, height: 28 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, "task-decision", truncate(data.analysis_brief?.decision, 150), { left: 900, top: 462, width: 300, height: 112 }, { fontSize: 21, color: INK });
  addNotes(slide);
}

// 3. Source and credibility.
{
  const slide = deck.slides.add();
  addLightHeader(slide, "The evidence is useful within clear boundaries", "Data source & ROCCC", 3);
  const source = (data.source_register || [])[0] || {};
  addText(slide, "source-file-label", "SOURCE", { left: 72, top: 200, width: 320, height: 26 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, "source-file", truncate(source.filename || data.original_filename, 58), { left: 72, top: 238, width: 500, height: 54 }, { fontSize: 26, bold: true, color: NAVY });
  addText(slide, "source-scale", `${Number(source.rows || data.schema_profile?.row_count || 0).toLocaleString()} rows  •  ${Number(source.columns || data.schema_profile?.column_count || 0).toLocaleString()} fields`, { left: 72, top: 308, width: 500, height: 36 }, { fontSize: 20, color: MUTED });
  addText(slide, "source-grain-label", "OBSERVATION GRAIN", { left: 72, top: 395, width: 320, height: 26 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, "source-grain", truncate(source.grain, 145), { left: 72, top: 433, width: 500, height: 96 }, { fontSize: 20, color: INK });
  addRule(slide, 636, 200, 5, ORANGE, 365);
  addText(slide, "roccc-label", "ROCCC & PERMISSION", { left: 680, top: 200, width: 460, height: 26 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, "roccc-copy", truncate(data.roccc_answers?.source_license, 420), { left: 680, top: 244, width: 500, height: 244 }, { fontSize: 20, color: INK });
  addText(slide, "validation-label", `VALIDATION: ${clean(data.validation_status, "Unknown").toUpperCase()}`, { left: 680, top: 520, width: 500, height: 34 }, { fontSize: 18, bold: true, color: data.validation_status === "Pass" ? TEAL : ORANGE });
  addNotes(slide);
}

// 4. Key findings overview.
{
  const slide = deck.slides.add();
  addLightHeader(slide, "The analysis points to a small set of decision-relevant findings", "Key findings", 4);
  const findingStatements = (data.findings || []).map((finding) => `${finding.finding_id}: ${finding.statement}`);
  bulletList(slide, findingStatements.length ? findingStatements : [data.analysis_summary], { left: 88, top: 205, width: 1080, fontSize: 23, gap: 92, maxItems: 4 });
  addNotes(slide);
}

// 5+. One evidence slide per supported calculation.
let slideNumber = 5;
for (const evidence of (data.evidence || []).slice(0, 6)) {
  const series = evidenceSeries(evidence);
  if (!series) continue;
  const slide = deck.slides.add();
  const finding = evidenceFinding(evidence.evidence_id);
  addLightHeader(slide, evidenceHeadline(evidence, series, finding), `Evidence ${evidence.evidence_id}`, slideNumber);

  const chartType = ["trend", "period_comparison"].includes(evidence.kind) ? "line" : "bar";
  const chartConfig = {
    position: { left: 72, top: 190, width: 765, height: 400 },
    categories: series.categories,
    series: [{
      name: clean(evidence.title, "Observed value"),
      values: series.values,
      fill: ORANGE,
      line: { style: "solid", fill: TEAL, width: 3 },
      marker: chartType === "line" ? { symbol: "circle", size: 6 } : undefined,
      valuesFormatCode: series.values.some((value) => !Number.isInteger(value)) ? "0.0" : "0",
    }],
    hasLegend: false,
    chartFill: PAPER,
    plotAreaFill: PAPER,
    chartLine: { style: "solid", fill: "none", width: 0 },
    plotAreaLine: { style: "solid", fill: "none", width: 0 },
    xAxis: {
      textStyle: { fill: MUTED, fontSize: chartType === "bar" ? 10 : 12 },
      line: { style: "solid", fill: RULE, width: 1 },
      majorGridlines: null,
    },
    yAxis: {
      textStyle: { fill: MUTED, fontSize: 12 },
      line: { style: "solid", fill: RULE, width: 1 },
      majorGridlines: { style: "solid", fill: RULE, width: 1 },
    },
    dataLabels: chartType === "bar" ? { showValue: true, position: "outEnd", textStyle: { fill: INK, fontSize: 12, bold: true } } : undefined,
  };
  if (chartType === "bar") chartConfig.barOptions = { direction: "bar", grouping: "clustered", gapWidth: 52 };
  if (chartType === "line") chartConfig.lineOptions = { smooth: false };
  slide.charts.add(chartType, chartConfig);

  addRule(slide, 878, 190, 5, TEAL, 400);
  addText(slide, `meaning-label-${slideNumber}`, "WHAT IT MEANS", { left: 914, top: 194, width: 280, height: 30 }, { fontSize: 15, bold: true, color: TEAL });
  addText(slide, `meaning-${slideNumber}`, truncate(finding?.implication || evidenceFallbackMeaning(evidence), 185), { left: 914, top: 242, width: 292, height: 150 }, { fontSize: 21, color: INK });
  addText(slide, `population-label-${slideNumber}`, "POPULATION", { left: 914, top: 435, width: 280, height: 26 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, `population-${slideNumber}`, truncate(evidence.population, 120), { left: 914, top: 470, width: 292, height: 80 }, { fontSize: 17, color: MUTED });
  addNotes(slide, `Method: ${clean(evidence.method)}\nCaveats: ${(evidence.caveats || []).join("; ") || "None recorded"}`);
  slideNumber += 1;
}

// Recommendations.
{
  const slide = deck.slides.add();
  addLightHeader(slide, "Move from evidence to owned, time-bound action", "Recommendations", slideNumber);
  const recommendations = (data.recommendations || []).slice(0, 3);
  recommendations.forEach((recommendation, index) => {
    const top = 190 + index * 142;
    addText(slide, `rec-number-${index}`, String(index + 1).padStart(2, "0"), { left: 72, top, width: 58, height: 44 }, { fontSize: 28, bold: true, color: ORANGE });
    addText(slide, `rec-action-${index}`, truncate(recommendation.action, 155), { left: 154, top, width: 720, height: 68 }, { fontSize: 23, bold: true, color: NAVY });
    addText(slide, `rec-owner-${index}`, `${clean(recommendation.owner_role)}  •  ${clean(recommendation.timeframe)}`, { left: 154, top: top + 78, width: 720, height: 30 }, { fontSize: 16, color: MUTED });
    addText(slide, `rec-impact-${index}`, `Expected impact\n${clean(recommendation.expected_impact)}`, { left: 930, top: top + 4, width: 250, height: 70 }, { fontSize: 17, bold: true, color: TEAL });
    if (index < recommendations.length - 1) addRule(slide, 154, top + 122, 1026, RULE, 2);
  });
  addNotes(slide);
  slideNumber += 1;
}

// Close with limitations and next steps, not a generic thank-you.
{
  const slide = deck.slides.add();
  slide.background.fill = NAVY;
  addText(slide, "close-kicker", "CONCLUSION & NEXT STEPS", { left: 72, top: 64, width: 500, height: 28 }, { fontSize: 14, bold: true, color: TEAL });
  addText(slide, "close-title", firstSentence(data.analysis_summary, 170), { left: 72, top: 128, width: 1080, height: 126 }, { fontSize: 38, bold: true, color: WHITE });
  addRule(slide, 72, 286, 110, ORANGE, 7);
  addText(slide, "close-limit-label", "WHAT THE DATA CANNOT YET ANSWER", { left: 72, top: 336, width: 500, height: 28 }, { fontSize: 15, bold: true, color: "#AFC0D6" });
  bulletList(slide, (data.limitations || []).slice(0, 3).map(shortLimitation), { left: 72, top: 386, width: 1080, fontSize: 19, color: "#DCE5F0", gap: 66, maxItems: 3, maxChars: 122 });
  addFooter(slide, slideNumber, "Decision and next steps", true);
  addNotes(slide);
}

await fs.mkdir(new URL(".", pathToFileURL(outputPath)), { recursive: true }).catch(() => {});
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(outputPath);
