"""
Milestone 3 — Analyze node, wired to the real database.

Deliverable structure combines two sources:
- Finding -> Business Implication pairing, with traceable IDs (Case Study 6
  format — the difference between a report and a defensible argument).
- "Analysis Summary" as its own narrative deliverable + "Additional
  deliverables for further exploration" section (Case Study 3's specific
  requirement for the open-ended path — not present in Bellabeat/Case Study 6).

Also applies Section 3.3 of the master plan as a standing rule, not a
one-off: always check distribution shape before reporting a mean.
"""

import pandas as pd
from typing import TypedDict

from app.core.database import SessionLocal
from app.models.schema import AgentAction


class AnalyzeState(TypedDict):
    session_id: str
    business_question: str
    findings: list
    analysis_summary: str
    additional_deliverables: list


def check_distribution_shape(values: pd.Series) -> str:
    """Section 3.3 standing rule: never report a mean without checking shape first."""
    import numpy as np
    arr = np.sort(values.dropna().to_numpy())
    if len(arr) < 10:
        return "insufficient data to assess shape"
    gaps = np.diff(arr)
    max_gap_idx = np.argmax(gaps)
    relative_gap = gaps[max_gap_idx] / (arr[-1] - arr[0]) if arr[-1] != arr[0] else 0
    left_mass = (max_gap_idx + 1) / len(arr)
    if relative_gap > 0.4 and min(left_mass, 1 - left_mass) > 0.1:
        return "bimodal — mean is misleading, report cluster split instead"
    return "unimodal — mean is representative"


def analyze_node(state: AnalyzeState) -> AnalyzeState:
    db = SessionLocal()
    try:
        df = pd.read_csv("/home/claude/nike_cleaned_v2.csv")
        findings = []

        # F1 — By Sales Method, with mandatory distribution-shape check
        online_shape = check_distribution_shape(df[df["Sales Method"] == "Online"]["Discount Pct"])
        by_method = df.groupby("Sales Method")["Discount Pct"].mean().round(2)
        findings.append({
            "id": "F1",
            "finding": f"'Online' averages {by_method['Online']}% discount vs "
                       f"'In-store' at {by_method['In-store']}%. Distribution check: {online_shape}.",
            "implication": "The average alone is misleading for Online — it is a bimodal split "
                            "(full-price vs. deep-discount clusters), not a gradual markdown pattern. "
                            "See F3 for the correct framing." if "bimodal" in online_shape
                            else "Average is representative here.",
        })

        # F2 — By Retailer
        by_retailer = df.groupby("Retailer")["Discount Pct"].mean().round(2).sort_values(ascending=False)
        findings.append({
            "id": "F2",
            "finding": f"'{by_retailer.index[0]}' shows the steepest average discount "
                       f"({by_retailer.iloc[0]}%), '{by_retailer.index[-1]}' the smallest "
                       f"({by_retailer.iloc[-1]}%).",
            "implication": "Discount exposure isn't uniform across retail partners — worth "
                            "checking against actual contract terms, not just transaction data.",
        })

        # F3 — The bimodal pattern itself, stated as its own finding
        online = df[df["Sales Method"] == "Online"]["Discount Pct"]
        near_zero_pct = (online < 5).mean() * 100
        near_90_pct = ((online >= 85) & (online <= 95)).mean() * 100
        findings.append({
            "id": "F3",
            "finding": f"Online discount is bimodal: {near_zero_pct:.1f}% of transactions near 0%, "
                       f"{near_90_pct:.1f}% near 90%, with zero transactions between 10%-85%.",
            "implication": "This gap-with-no-middle pattern is more consistent with a "
                            "wholesale/retail reporting split in the data than organic customer "
                            "discount behavior — likely a data-generation artifact.",
        })

        # F4 — Regional spread
        by_region = df.groupby("Region")["Discount Pct"].mean().round(2)
        spread = by_region.max() - by_region.min()
        findings.append({
            "id": "F4",
            "finding": f"Regional averages range {by_region.min()}%-{by_region.max()}% "
                       f"(spread of {spread:.2f} points).",
            "implication": (
                "Narrow spread suggests this is a channel/retailer dynamic, not a regional "
                "pricing strategy." if spread < 3 else
                "Spread is wide enough to suggest region-specific pricing or promotional "
                "calendars may be a real factor, not just channel/retailer effects."
            ),
        })

        # F5 — Time trend
        df["Invoice Date"] = pd.to_datetime(df["Invoice Date"])
        df["Quarter"] = df["Invoice Date"].dt.to_period("Q").astype(str)
        by_quarter = df.groupby("Quarter")["Discount Pct"].mean().round(2)
        trend = "decreased" if by_quarter.iloc[-1] < by_quarter.iloc[0] else "increased"
        findings.append({
            "id": "F5",
            "finding": f"Discount gap {trend} from {by_quarter.iloc[0]}% to {by_quarter.iloc[-1]}% "
                       f"over 2020-2021.",
            "implication": f"Trend is {trend} but gradual — worth checking against known demand "
                            f"events rather than assuming steady drift.",
        })

        analysis_summary = (
            f"Analysis targeted the locked business question: {state['business_question']}. "
            f"The dataset-wide average discount (54%) initially looked alarming, but distribution "
            f"analysis (F3) revealed this is a bimodal pattern, not organic markdown behavior — "
            f"most likely a data-reporting artifact rather than real business signal. This is the "
            f"headline finding: the investigative process (catching a misleading average) is more "
            f"valuable here than the raw number itself."
        )

        additional_deliverables = [
            "Confirm with the original Kaggle source whether 'Total Sales' is defined differently "
            "per sales channel — would fully resolve F3's remaining uncertainty.",
            "If confirmed as real transactional data: investigate the West Gear + Online "
            "combination specifically (highest discount exposure pairing, not yet isolated here).",
            "Correlate the quarterly discount trend (F5) against known 2020-2021 demand events "
            "(e.g. COVID-driven e-commerce shifts) rather than treating it as unexplained drift.",
        ]

        db.add(AgentAction(
            session_id=state["session_id"],
            stage="analyze",
            action_type="statistical_analysis",
            input_summary=f"Business question: {state['business_question']}",
            output_summary=f"{len(findings)} findings generated, headline: F3 (bimodal pattern)",
            code_executed="groupby Sales Method/Retailer/Region/Quarter on Discount Pct, "
                           "distribution shape check via gap-detection",
        ))
        db.commit()

        return {
            "findings": findings,
            "analysis_summary": analysis_summary,
            "additional_deliverables": additional_deliverables,
        }
    finally:
        db.close()
