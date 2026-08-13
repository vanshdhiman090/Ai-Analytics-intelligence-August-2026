"""Share phase: render chart artifacts directly from validated evidence."""

from pathlib import Path
import re
from textwrap import shorten
from typing import TypedDict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import AgentAction, Artifact
from app.services.run_state import mark_stage


COLORS = {
    "ink": "#17213A",
    "primary": "#2F5EA8",
    "primary_open": "#DCE7F7",
    "gold": "#C58A28",
    "gold_open": "#F6E9CB",
    "neutral": "#69758A",
    "grid": "#DCE3EC",
    "paper": "#FFFFFF",
}


class ShareState(TypedDict, total=False):
    session_id: str
    evidence: list
    findings: list
    chart_paths: dict


def _number(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    absolute = abs(float(value))
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}k"
    if absolute >= 10:
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _subtitle(evidence: dict, detail: str = "") -> str:
    population = shorten(str(evidence.get("population") or "Population not stated"), width=105, placeholder="…")
    return " · ".join(item for item in (detail, population) if item)


def _display_title(evidence: dict) -> str:
    title = str(evidence.get("title") or "Analysis result")
    match = re.match(r"^(sum|mean|median|min|max|count) of (.+) by (.+)$", title, re.IGNORECASE)
    if match:
        aggregation, metric, dimension = match.groups()
        return f"{metric} by {dimension} ({aggregation.lower()})"
    return title[:1].upper() + title[1:]


def chart_metadata(evidence: dict) -> dict[str, str]:
    """Describe the visual so every chart stays traceable and accessible."""
    kind = evidence.get("kind")
    rows = evidence.get("rows") or []
    chart_type = {
        "grouped_aggregate": "ranked horizontal bar",
        "trend": "line" if len(rows) >= 8 else "period bar",
        "period_comparison": "period comparison bar",
        "distribution": "quantile range",
        "outlier_analysis": "outlier diagnostic",
        "correlation": "correlation coefficient scale",
        "kpi_ratio": "KPI ratio bar",
        "statistical_comparison": "two-group effect comparison",
        "segment_change": "diverging contribution bar",
    }.get(kind, "unsupported")
    return {
        "chart_type": chart_type,
        "subtitle": _subtitle(evidence),
        "alt_text": (
            f"{_display_title(evidence)}. {chart_type} based on "
            f"{evidence.get('population') or 'the stated analysis population'}."
        ),
    }


def _style_axes(ax) -> None:
    ax.set_facecolor(COLORS["paper"])
    ax.tick_params(colors=COLORS["neutral"], labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(COLORS["grid"])
    ax.grid(axis="x", color=COLORS["grid"], linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)


def _decorate(fig, ax, evidence: dict, detail: str) -> None:
    fig.suptitle(
        _display_title(evidence),
        x=0.075,
        y=0.97,
        ha="left",
        color=COLORS["ink"],
        fontsize=15,
        fontweight="bold",
    )
    fig.text(0.075, 0.91, _subtitle(evidence, detail), ha="left", color=COLORS["neutral"], fontsize=9)
    fig.text(
        0.075,
        0.025,
        f"{evidence.get('evidence_id', 'Evidence')} · {evidence.get('method', 'Validated calculation')}",
        ha="left",
        color=COLORS["neutral"],
        fontsize=8,
    )
    _style_axes(ax)


def render_evidence_chart(evidence: dict, destination: Path) -> bool:
    rows = evidence.get("rows", [])
    kind = evidence.get("kind")
    if not rows or kind == "summary":
        return False

    fig, ax = plt.subplots(figsize=(9.2, 5.2), facecolor=COLORS["paper"])
    if kind == "grouped_aggregate":
        category_fields = evidence.get("diagnostics", {}).get("dimension_columns") or [evidence["columns"][0]]
        ranked = sorted(
            ((" • ".join(str(row.get(field, "Unknown")) for field in category_fields), row.get("value")) for row in rows if isinstance(row.get("value"), (int, float))),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            plt.close(fig)
            return False
        if len(ranked) > 12:
            shown = ranked[:6] + ranked[-6:]
            detail = f"Top 6 and bottom 6 of {len(ranked)} categories; sorted by observed value"
            colors = [COLORS["primary"]] * 6 + [COLORS["gold_open"]] * 6
        else:
            shown = ranked
            detail = f"{len(shown)} categories; sorted by observed value"
            colors = [COLORS["primary"]] + [COLORS["primary_open"]] * (len(shown) - 1)
        labels = [shorten(label, width=30, placeholder="…") for label, _ in shown]
        values = [value for _, value in shown]
        bars = ax.barh(labels, values, color=colors, edgecolor=COLORS["primary"], linewidth=0.7)
        ax.invert_yaxis()
        ax.axvline(0, color=COLORS["ink"], linewidth=0.9)
        value_span = max(values) - min(0, min(values)) or 1
        for bar, value in zip(bars, values):
            x = value + (value_span * 0.012 if value >= 0 else -value_span * 0.012)
            ax.text(x, bar.get_y() + bar.get_height() / 2, _number(value), va="center", ha="left" if value >= 0 else "right", fontsize=8.5, color=COLORS["ink"])
        ax.set_xlabel("Observed value", color=COLORS["neutral"])
        ax.margins(x=0.16)
        _decorate(fig, ax, evidence, detail)
    elif kind in {"trend", "period_comparison"}:
        points = [(str(row.get("period")), row.get("value")) for row in rows if isinstance(row.get("value"), (int, float))]
        if not points:
            plt.close(fig)
            return False
        labels = [item[0] for item in points]
        values = [item[1] for item in points]
        if len(points) >= 8:
            ax.plot(labels, values, marker="o", markersize=4.5, linewidth=2.2, color=COLORS["primary"], markerfacecolor=COLORS["paper"], markeredgewidth=1.5)
            detail = f"{len(points)} observed periods"
        else:
            bars = ax.bar(labels, values, color=COLORS["primary_open"], edgecolor=COLORS["primary"], linewidth=0.9)
            for bar, value in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, value, _number(value), ha="center", va="bottom", fontsize=8, color=COLORS["ink"])
            detail = f"{len(points)} discrete periods; bars used because the series is too short for a trend line"
        ax.tick_params(axis="x", rotation=45)
        ax.set_ylabel("Observed value", color=COLORS["neutral"])
        _decorate(fig, ax, evidence, detail)
    elif kind == "distribution":
        quantiles = {round(float(row.get("quantile")), 2): row.get("value") for row in rows if isinstance(row.get("value"), (int, float)) and row.get("quantile") is not None}
        required = (0.0, 0.25, 0.5, 0.75, 1.0)
        if not all(key in quantiles for key in required):
            plt.close(fig)
            return False
        low, q1, median, q3, high = (quantiles[key] for key in required)
        ax.hlines(0, low, high, color=COLORS["neutral"], linewidth=2)
        ax.vlines([low, high], -0.12, 0.12, color=COLORS["neutral"], linewidth=2)
        ax.add_patch(Rectangle((q1, -0.28), q3 - q1, 0.56, facecolor=COLORS["primary_open"], edgecolor=COLORS["primary"], linewidth=1.2))
        ax.vlines(median, -0.34, 0.34, color=COLORS["primary"], linewidth=3)
        ax.text(
            0.5,
            0.82,
            f"Min {_number(low)}   ·   Q1 {_number(q1)}   ·   Median {_number(median)}   ·   Q3 {_number(q3)}   ·   Max {_number(high)}",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=9,
            color=COLORS["ink"],
            bbox={"boxstyle": "round,pad=0.45", "facecolor": COLORS["paper"], "edgecolor": COLORS["grid"]},
        )
        ax.set_ylim(-0.75, 0.75)
        ax.set_yticks([])
        ax.set_xlabel("Observed value", color=COLORS["neutral"])
        _decorate(fig, ax, evidence, "Five-number quantile summary; box spans the middle 50%")
    elif kind == "correlation":
        value = rows[0].get("correlation")
        if not isinstance(value, (int, float)):
            plt.close(fig)
            return False
        ax.axvspan(-1, 0, color=COLORS["gold_open"], alpha=0.65)
        ax.axvspan(0, 1, color=COLORS["primary_open"], alpha=0.65)
        ax.axvline(0, color=COLORS["ink"], linewidth=1)
        ax.hlines(0, -1, 1, color=COLORS["neutral"], linewidth=1.3)
        ax.scatter([value], [0], s=180, color=COLORS["primary"], edgecolor=COLORS["ink"], linewidth=1, zorder=3)
        ax.text(value, 0.19, f"r = {value:.2f}", ha="center", fontsize=12, fontweight="bold", color=COLORS["ink"])
        ax.text(-0.98, -0.24, "Negative association", ha="left", color=COLORS["neutral"], fontsize=8.5)
        ax.text(0.98, -0.24, "Positive association", ha="right", color=COLORS["neutral"], fontsize=8.5)
        ax.set_xlim(-1, 1)
        ax.set_ylim(-0.45, 0.45)
        ax.set_yticks([])
        ax.set_xlabel("Pearson correlation coefficient", color=COLORS["neutral"])
        pair_count = rows[0].get("pair_count")
        _decorate(fig, ax, evidence, f"Complete numeric pairs: {pair_count or 'not stated'}; association does not establish causation")
    elif kind == "kpi_ratio":
        category = evidence["columns"][0]
        points = [(str(row.get(category, "Overall")), row.get("ratio")) for row in rows if isinstance(row.get("ratio"), (int, float))]
        if not points:
            plt.close(fig)
            return False
        labels, values = zip(*points)
        bars = ax.barh(labels, values, color=COLORS["primary_open"], edgecolor=COLORS["primary"])
        ax.invert_yaxis()
        for bar, value in zip(bars, values):
            ax.text(value, bar.get_y() + bar.get_height()/2, _number(value), va="center", ha="left", fontsize=8, color=COLORS["ink"])
        ax.set_xlabel(f"Ratio (scale {evidence.get('diagnostics', {}).get('scale', 100)})", color=COLORS["neutral"])
        _decorate(fig, ax, evidence, f"{len(points)} ratio result(s); denominators retained in evidence")
    elif kind == "statistical_comparison":
        row = rows[0]
        labels = [str(row.get("baseline_group")), str(row.get("comparison_group"))]
        values = [row.get("baseline_mean"), row.get("comparison_mean")]
        if not all(isinstance(value, (int, float)) for value in values):
            plt.close(fig)
            return False
        bars = ax.bar(labels, values, color=[COLORS["neutral"], COLORS["primary"]], alpha=.9)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x()+bar.get_width()/2, value, _number(value), ha="center", va="bottom", fontsize=9, color=COLORS["ink"])
        _decorate(fig, ax, evidence, f"Cohen's d: {_number(row.get('cohens_d'))}; permutation p: {_number(row.get('permutation_p_value'))}")
    elif kind == "segment_change":
        category = evidence["columns"][0]
        points = [(str(row.get(category)), row.get("absolute_change")) for row in rows if isinstance(row.get("absolute_change"), (int, float))]
        if not points:
            plt.close(fig)
            return False
        labels, values = zip(*points)
        colors = [COLORS["primary"] if value >= 0 else COLORS["gold"] for value in values]
        ax.barh(labels, values, color=colors, alpha=.9)
        ax.invert_yaxis()
        ax.axvline(0, color=COLORS["ink"], linewidth=.9)
        ax.set_xlabel("Absolute contribution to change", color=COLORS["neutral"])
        _decorate(fig, ax, evidence, f"{len(points)} displayed segments; positive and negative contributions")
    else:
        plt.close(fig)
        return False

    fig.subplots_adjust(left=0.19, right=0.95, top=0.82, bottom=0.17)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight", facecolor=COLORS["paper"])
    plt.close(fig)
    return True


def share_node(state: ShareState) -> ShareState:
    mark_stage(state["session_id"], "share")
    artifact_dir = settings.DATA_DIR / "runs" / state["session_id"] / "artifacts"
    chart_paths: dict[str, str] = {}
    db = SessionLocal()
    try:
        for evidence in state.get("evidence", []):
            evidence_id = evidence["evidence_id"]
            destination = artifact_dir / f"{evidence_id.lower()}.png"
            if not render_evidence_chart(evidence, destination):
                continue
            chart_paths[evidence_id] = str(destination)
            metadata = chart_metadata(evidence)
            db.add(
                Artifact(
                    session_id=state["session_id"],
                    type="chart",
                    file_path=str(destination),
                    metadata_={"evidence_id": evidence_id, "title": evidence.get("title"), **metadata},
                )
            )

        db.add(
            AgentAction(
                session_id=state["session_id"],
                stage="share",
                action_type="evidence_chart_generation",
                input_summary=f"{len(state.get('evidence', []))} evidence records",
                output_summary=f"Generated {len(chart_paths)} evidence-linked charts",
            )
        )
        db.commit()
    finally:
        db.close()
    return {"chart_paths": chart_paths}
