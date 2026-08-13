import pandas as pd

from app.agent.subagents.analyze_agent import AnalyzeAgent
from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.services.pandas_tools import QueryTool


def test_root_cause_uses_validated_analysis_contract(monkeypatch):
    expected = {
        "analysis_plan": {"operations": []},
        "evidence": [{"evidence_id": "E1"}],
        "findings": [{"finding_id": "F1"}],
        "analysis_summary": "No additive decomposition was approved.",
    }
    monkeypatch.setattr(AnalyzeAgent, "run_analysis", lambda self, state: expected)

    result = RootCauseAgent().execute({"session_id": "s1"})

    assert result["evidence"] == expected["evidence"]
    assert result["root_cause_report"]["status"] == "abstained"
    assert result["root_cause_report"]["conclusion"]["causal_claim_allowed"] is False


def test_query_tool_has_no_optional_markdown_dependency():
    result = QueryTool(pd.DataFrame({"Region": ["A", "B"], "Sales": [10, 20]})).query_dataset(
        groupby=["Region"], metrics={"Sales": "sum"}
    )

    assert "Region,Sales" in result
    assert "A,10" in result
