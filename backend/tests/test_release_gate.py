from app.evals.release_gate import combine_release_status


def analytical(ready=True):
    return {"release_ready": ready, "case_count": 27, "passed_count": 27 if ready else 26, "failed_count": 0 if ready else 1, "category_scores": {"calculation": 1.0}}


def test_release_requires_analytics_and_browser_journeys():
    combined = combine_release_status(analytical(), {"release_ready": True, "status": "passed", "case_count": 3, "passed_count": 3})
    assert combined["release_ready"] is True
    assert combined["case_count"] == 30
    assert combined["passed_count"] == 30
    assert combined["category_scores"]["browser_journey"] == 1


def test_stale_browser_gate_blocks_release():
    combined = combine_release_status(analytical(), {"release_ready": False, "status": "stale", "case_count": 3, "passed_count": 3})
    assert combined["release_ready"] is False
    assert combined["browser_release_ready"] is False
    assert combined["category_scores"]["browser_journey"] == 0
