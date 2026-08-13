from app.evals.investigation_conclusion_runner import (
    run_answer_keyed,
    run_metamorphic,
)


def test_answer_keyed_conclusion_benchmark_uses_live_agent_path():
    result = run_answer_keyed()

    assert result["case_count"] == 10
    assert result["passed_count"] == 10
    assert result["all_passed"] is True


def test_provider_failure_has_semantic_conclusion_parity():
    result = run_answer_keyed()

    assert result["provider_fallback_parity"] is True


def test_tie_safe_metamorphic_invariants():
    result = run_metamorphic()

    assert result["all_passed"] is True
    assert all(result["checks"].values())

