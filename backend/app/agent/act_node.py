"""
Milestone 5 — Act node, wired to the real database.

Rules enforced (not optional):
1. Every recommendation cites finding ID(s). No orphaned claims.
2. Recommendations branch: real data vs. practice/synthetic data, since F3
   left that genuinely unresolved.
3. Known Limitations is a mandatory section.

Recommendation count follows Case Study 3's open "top high-level
recommendations" framing rather than Bellabeat's fixed "top three" —
this dataset's findings support 3 natural recommendations, kept as-is
rather than padded or trimmed to hit a fixed number.
"""

from typing import TypedDict

from app.core.database import SessionLocal
from app.models.schema import Artifact, AgentAction


class ActState(TypedDict):
    session_id: str
    findings: list
    recommendations: list
    limitations: list


def act_node(state: ActState) -> ActState:
    db = SessionLocal()
    try:
        recommendations = [
            {
                "priority": 1,
                "recommendation": "Confirm with the data source whether 'Total Sales' reflects "
                                   "wholesale vs. retail reporting for Online/Outlet channels "
                                   "before acting on any discount pattern in this dataset.",
                "supporting_findings": ["F3"],
                "type": "data-integrity",
            },
            {
                "priority": 2,
                "recommendation": "IF confirmed real data: investigate the West Gear + Online "
                                   "combination specifically — the most exposed pairing in the "
                                   "dataset, worth reviewing against actual contract terms.",
                "supporting_findings": ["F2", "F3"],
                "type": "conditional-business",
            },
            {
                "priority": 3,
                "recommendation": "IF confirmed practice/synthetic data: treat this analysis as a "
                                   "demonstrated capability (catching a misleading average, "
                                   "isolating a bimodal distribution, tracing it to a likely "
                                   "reporting artifact) rather than real business insight.",
                "supporting_findings": ["F1", "F3"],
                "type": "conditional-portfolio",
            },
        ]

        limitations = [
            "Could not confirm the original Kaggle source page or license terms — no verified "
            "link was available to check collection methodology.",
            "Cannot definitively confirm real vs. synthetic data; the bimodal pattern (F3) is "
            "strong circumstantial evidence for synthetic, not proof.",
            "'Total Sales' field definition is undocumented — the discount metric used "
            "throughout is inferred, not a field provided directly by the source.",
            "Regional and time-based findings (F4, F5) inherit the same data-integrity "
            "uncertainty as F1/F3 and should be re-validated once the source is confirmed.",
        ]

        # Validation: enforce no orphaned claims before writing anything
        finding_ids = {f["id"] for f in state["findings"]}
        for rec in recommendations:
            for fid in rec["supporting_findings"]:
                assert fid in finding_ids, f"Recommendation cites unknown finding {fid}"

        report_text = "ACT — RECOMMENDATIONS\n\n"
        for rec in recommendations:
            report_text += (
                f"[Priority {rec['priority']}] {rec['recommendation']}\n"
                f"  Supporting findings: {', '.join(rec['supporting_findings'])}\n\n"
            )
        report_text += "KNOWN LIMITATIONS\n\n" + "\n".join(f"- {l}" for l in limitations)

        report_path = "/home/claude/act_report_v2.txt"
        with open(report_path, "w") as f:
            f.write(report_text)

        db.add(Artifact(
            session_id=state["session_id"],
            type="report",
            file_path=report_path,
            metadata_={"recommendation_count": len(recommendations), "limitation_count": len(limitations)},
        ))

        db.add(AgentAction(
            session_id=state["session_id"],
            stage="act",
            action_type="recommendation_generation",
            input_summary=f"{len(state['findings'])} findings",
            output_summary=f"{len(recommendations)} recommendations (all traced to finding IDs), "
                            f"{len(limitations)} limitations documented",
        ))
        db.commit()

        return {"recommendations": recommendations, "limitations": limitations}
    finally:
        db.close()
