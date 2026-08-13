import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent


def _analysis_result():
    return {
        "analysis_plan": {
            "operations": [
                {
                    "operation_id": "OP1",
                    "kind": "segment_change",
                    "metric_column": "value",
                    "dimension_column": "segment",
                    "time_column": "date",
                    "time_grain": "auto",
                }
            ]
        },
        "evidence": [
            {
                "evidence_id": "E1",
                "operation_id": "OP1",
                "title": "Value change by segment",
                "quality_status": "ready",
                "diagnostics": {"time_grain": "month"},
            }
        ],
        "findings": [],
        "analysis_summary": "Observed movement was decomposed by segment.",
        "additional_deliverables": [],
    }


def test_root_cause_agent_maps_approved_segment_change_into_typed_report(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-02-01", "2026-02-02"],
            "segment": ["A", "B", "A", "B"],
            "value": [600.0, 400.0, 510.0, 390.0],
        }
    )
    monkeypatch.setattr(
        "app.agent.subagents.root_cause_agent.AnalyzeAgent.run_analysis",
        lambda _self, _state: _analysis_result(),
    )
    monkeypatch.setattr(
        "app.agent.subagents.root_cause_agent.load_dataframe", lambda _path: frame
    )

    result = RootCauseAgent().execute(
        {
            "cleaned_path": "unused.csv",
            "schema_profile": {},
            "period_completeness_confirmed": True,
        }
    )

    assert result["root_cause_report"]["incident"]["absolute_change"] == -100.0
    assert result["root_cause_report"]["conclusion"]["determination"] == "mathematical_driver_identified"
    assert result["root_cause_report"]["conclusion"]["causal_claim_allowed"] is False
    assert result["metric_semantics"]["status"] == "generic_metric"


def test_root_cause_agent_abstains_when_plan_has_no_additive_decomposition(monkeypatch):
    result_without_segment_change = _analysis_result()
    result_without_segment_change["analysis_plan"] = {"operations": []}
    monkeypatch.setattr(
        "app.agent.subagents.root_cause_agent.AnalyzeAgent.run_analysis",
        lambda _self, _state: result_without_segment_change,
    )

    result = RootCauseAgent().execute({"cleaned_path": "unused.csv", "schema_profile": {}})

    assert result["root_cause_report"]["status"] == "abstained"
    assert result["root_cause_report"]["conclusion"]["causal_claim_allowed"] is False


def test_revenue_semantics_never_guess_currency_or_timezone():
    definition = {
        "metric_name": "net_revenue",
        "metric_column": "net_revenue",
        "time_column": "order_date",
        "driver_column": "channel",
    }

    semantics = RootCauseAgent._metric_semantics({"schema_profile": {}}, definition)

    assert semantics["status"] == "abstained"
    assert semantics["missing_policy_fields"] == [
        "revenue_reporting_currency",
        "revenue_timezone",
    ]


def test_revenue_semantic_abstention_blocks_root_cause_execution(monkeypatch):
    revenue_result = _analysis_result()
    operation = revenue_result["analysis_plan"]["operations"][0]
    operation["metric_column"] = "net_revenue"
    monkeypatch.setattr(
        "app.agent.subagents.root_cause_agent.AnalyzeAgent.run_analysis",
        lambda _self, _state: revenue_result,
    )
    monkeypatch.setattr(
        "app.agent.subagents.root_cause_agent.build_root_cause_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("RCA must not execute")),
    )

    result = RootCauseAgent().execute({"cleaned_path": "unused.csv", "schema_profile": {}})

    assert result["metric_semantics"]["status"] == "abstained"
    assert result["root_cause_report"]["status"] == "abstained"
