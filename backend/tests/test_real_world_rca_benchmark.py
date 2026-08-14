from app.evals.real_world_rca_benchmark_runner import run_benchmark


def test_real_world_rca_benchmarks_pass_through_public_service():
    result = run_benchmark()

    assert result["release_ready"] is True
    assert result["provider_mode"] == "deterministic_fallback"
    assert result["case_count"] == 5
    assert result["passed_count"] == 5
    assert not [case for case in result["results"] if case["mismatches"]]


def test_all_selected_path_benchmarks_are_row_order_invariant():
    result = run_benchmark()

    path_cases = [
        case
        for case in result["results"]
        if case["expected_engine_output"]["path"]
    ]
    assert path_cases
    assert all(case["row_shuffle_invariant"] is True for case in path_cases)
