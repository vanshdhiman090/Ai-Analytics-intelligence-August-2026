"""
Milestone 4 — Share node, wired to the real database.

Fully automated per locked MVP scope — no checkpoint needed here.
Chart-type selection is rule-based (Section: Share design), not left to
an LLM to decide freely. Headline finding (F3, the bimodal pattern) gets
a purpose-built chart; supporting findings get smaller standard charts —
matching the "one chart carries the story" principle from earlier design.
"""

import pandas as pd
import matplotlib.pyplot as plt
from typing import TypedDict

from app.core.database import SessionLocal
from app.models.schema import Artifact, AgentAction

COLORS = {"primary": "#0072B2", "secondary": "#D55E00", "neutral": "#999999", "accent": "#009E73"}
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                      "figure.facecolor": "white"})


class ShareState(TypedDict):
    session_id: str
    findings: list
    chart_paths: dict


def share_node(state: ShareState) -> ShareState:
    db = SessionLocal()
    try:
        df = pd.read_csv("/home/claude/nike_cleaned_v2.csv")
        chart_paths = {}

        # Headline chart — F3, the bimodal pattern. Full visual weight.
        online = df[df["Sales Method"] == "Online"]["Discount Pct"].dropna()
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.hist(online, bins=40, color=COLORS["primary"], edgecolor="white")
        ax.axvspan(0, 10, alpha=0.15, color=COLORS["accent"], label="Full-price cluster")
        ax.axvspan(85, 95, alpha=0.15, color=COLORS["secondary"], label="Deep-discount cluster")
        ax.set_xlabel("Implied Discount (%)")
        ax.set_ylabel("Number of Transactions")
        ax.set_title("Online Channel: Bimodal Pattern, Not a Gradual Discount", fontweight="bold")
        ax.legend(loc="upper center", frameon=False)
        plt.tight_layout()
        path = "/home/claude/artifact_f3_headline.png"
        plt.savefig(path, dpi=150)
        plt.close()
        chart_paths["F3"] = path

        # Supporting chart — F1/F2, categorical comparison, horizontal bar
        fig, ax = plt.subplots(figsize=(7, 3.5))
        by_method = df.groupby("Sales Method")["Discount Pct"].mean().sort_values()
        ax.barh(by_method.index, by_method.values, color=COLORS["neutral"])
        ax.set_xlabel("Average Discount %")
        ax.set_title("Average Discount by Sales Method", fontsize=10)
        plt.tight_layout()
        path = "/home/claude/artifact_f1_method.png"
        plt.savefig(path, dpi=150)
        plt.close()
        chart_paths["F1"] = path

        # Supporting chart — F5, time trend, line
        df["Invoice Date"] = pd.to_datetime(df["Invoice Date"])
        df["Quarter"] = df["Invoice Date"].dt.to_period("Q").astype(str)
        fig, ax = plt.subplots(figsize=(8, 3.5))
        by_q = df.groupby("Quarter")["Discount Pct"].mean()
        ax.plot(by_q.index, by_q.values, marker="o", color=COLORS["primary"])
        ax.set_ylabel("Average Discount %")
        ax.set_title("Discount Trend, 2020-2021", fontsize=10)
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        path = "/home/claude/artifact_f5_trend.png"
        plt.savefig(path, dpi=150)
        plt.close()
        chart_paths["F5"] = path

        for finding_id, path in chart_paths.items():
            db.add(Artifact(
                session_id=state["session_id"],
                type="chart",
                file_path=path,
                metadata_={"finding_id": finding_id},
            ))

        db.add(AgentAction(
            session_id=state["session_id"],
            stage="share",
            action_type="chart_generation",
            input_summary=f"{len(state['findings'])} findings from Analyze stage",
            output_summary=f"Generated {len(chart_paths)} charts: {list(chart_paths.keys())}",
        ))
        db.commit()

        return {"chart_paths": chart_paths}
    finally:
        db.close()
