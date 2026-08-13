import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.domain.root_cause_contracts import HypothesisProposalSet, InvestigationFilter, SingleLevelInvestigationRequest
from app.services.hypothesis_planner import plan_hypotheses


def request(**overrides):
    values = {
        "investigation_id": "planner-test",
        "goal": "Investigate the revenue decline",
        "kpi": {"metric_name": "Revenue", "metric_column": "revenue", "time_column": "date", "aggregation": "sum", "time_grain": "month"},
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": ["country", "device", "customer_type"],
        "hypothesis_planning_enabled": True,
    }
    values.update(overrides)
    return SingleLevelInvestigationRequest.model_validate(values)


def planner_output(proposals):
    def generate(_, output_type):
        return output_type.model_validate({"proposals": proposals})
    return generate


def test_partial_validation_keeps_valid_proposals_and_appends_omissions():
    record = plan_hypotheses(
        request(), schema=(("country", "string"),), allowed_dimensions=("country", "device", "customer_type"), planning_id=1,
        generator=planner_output([
            {"target_dimension": "device", "reason_code": "kpi_relevance", "brief_reason": "Useful approved cut"},
            {"target_dimension": "marketing_campaign", "reason_code": "kpi_relevance"},
            {"target_dimension": "customer_type", "reason_code": "business_structure"},
        ]),
    )
    assert [item.target_dimension for item in record.validated_proposals] == ["device", "customer_type", "country"]
    assert [item.source for item in record.validated_proposals] == ["llm", "llm", "deterministic_fallback"]
    assert record.planner_mode == "llm_with_fallback"
    assert record.rejected_proposals[0].rejection_reason == "dimension_not_allowed"
    assert all("may contain a segment" in item.statement for item in record.validated_proposals)


def test_history_is_exact_scope_not_global_dimension_blacklist():
    output = planner_output([{"target_dimension": "device", "reason_code": "current_scope_relevance"}])
    global_record = plan_hypotheses(request(), schema=(), allowed_dimensions=("country", "device"), already_tested_dimensions=("device",), planning_id=1, generator=output)
    assert global_record.rejected_proposals[0].rejection_reason == "dimension_already_tested_in_scope"
    germany_record = plan_hypotheses(request(), schema=(), filter_path=(InvestigationFilter(dimension="country", segment="Germany"),), allowed_dimensions=("device",), planning_id=2, generator=output)
    assert germany_record.validated_proposals[0].target_dimension == "device"
    assert germany_record.validated_proposals[0].source == "llm"


def test_unsafe_numeric_and_causal_brief_reasons_are_rejected():
    record = plan_hypotheses(
        request(), schema=(), allowed_dimensions=("device", "country"), planning_id=1,
        generator=planner_output([
            {"target_dimension": "device", "reason_code": "kpi_relevance", "brief_reason": "Device caused a 20% decline"},
            {"target_dimension": "country", "reason_code": "kpi_relevance", "brief_reason": "Relevant approved cut"},
        ]),
    )
    assert record.rejected_proposals[0].rejection_reason == "unsupported_numeric_claim"
    assert record.validated_proposals[0].target_dimension == "country"


def test_no_valid_llm_proposal_uses_complete_deterministic_fallback():
    record = plan_hypotheses(
        request(), schema=(), allowed_dimensions=("country", "device"), planning_id=1,
        generator=planner_output([{"target_dimension": "unknown_dimension", "reason_code": "kpi_relevance"}]),
    )
    assert record.planner_mode == "deterministic_fallback"
    assert record.fallback_reason == "no_valid_proposals"
    assert [item.target_dimension for item in record.validated_proposals] == ["country", "device"]


def _frame():
    return pd.DataFrame([
        {"date": "2026-01-01", "country": "Germany", "device": "Mobile", "customer_type": "Returning", "revenue": 100},
        {"date": "2026-02-01", "country": "Germany", "device": "Mobile", "customer_type": "Returning", "revenue": 40},
        {"date": "2026-01-01", "country": "France", "device": "Desktop", "customer_type": "New", "revenue": 100},
        {"date": "2026-02-01", "country": "France", "device": "Desktop", "customer_type": "New", "revenue": 90},
    ])


def test_root_cause_agent_records_llm_planning_but_math_still_selects_driver(tmp_path, monkeypatch):
    path = tmp_path / "input.csv"; _frame().to_csv(path, index=False)
    monkeypatch.setattr("app.services.hypothesis_planner.generate_structured", planner_output([
        {"target_dimension": "device", "reason_code": "kpi_relevance"},
        {"target_dimension": "marketing_campaign", "reason_code": "business_structure"},
    ]))
    result = RootCauseAgent().execute({"cleaned_path": str(path), "investigation_request": request().model_dump(mode="json")})["investigation_state"]
    record = result["hypothesis_planning_records"][0]
    assert result["leading_dimension"] == "country"
    assert record["validated_proposals"][0]["target_dimension"] == "device"
    assert record["rejected_proposals"][0]["rejection_reason"] == "dimension_not_allowed"


def test_provider_failure_falls_back_and_root_cause_agent_still_completes(tmp_path, monkeypatch):
    path = tmp_path / "input.csv"; _frame().to_csv(path, index=False)
    monkeypatch.setattr("app.services.hypothesis_planner.generate_structured", lambda *_: (_ for _ in ()).throw(RuntimeError("provider unavailable")))
    result = RootCauseAgent().execute({"cleaned_path": str(path), "investigation_request": request().model_dump(mode="json")})["investigation_state"]
    record = result["hypothesis_planning_records"][0]
    assert result["outcome"] == "strongest_supported_driver"
    assert record["planner_mode"] == "deterministic_fallback"
    assert record["fallback_reason"] == "provider_failure"
