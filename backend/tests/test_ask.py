from app.agent.ask_node import resolve_business_task


def test_confirm_keeps_the_proposed_question():
    proposed = "Which segment contributed most to the revenue decline?"
    assert resolve_business_task("Confirm", proposed) == proposed
    assert resolve_business_task("yes", proposed) == proposed


def test_revision_replaces_the_proposed_question():
    revision = "Which region contributed most to the revenue decline?"
    assert resolve_business_task(revision, "Original question") == revision
