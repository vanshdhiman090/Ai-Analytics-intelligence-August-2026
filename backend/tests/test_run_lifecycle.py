from types import SimpleNamespace

import pytest
from langgraph.errors import EmptyInputError

from app.services.run_manager import (
    RecoveryInputMissingError,
    derive_run_outcome,
    invoke_pipeline,
    safe_error_message,
)


class FakeGraph:
    def __init__(self, *, checkpoint_exists: bool):
        self.checkpoint_exists = checkpoint_exists
        self.inputs = []

    def invoke(self, value, config):
        self.inputs.append(value)
        if value is None and not self.checkpoint_exists:
            raise EmptyInputError("Received no input for __start__")
        return {"received": value}


def test_completed_graph_result_maps_to_complete():
    assert derive_run_outcome({"findings": []}) == ("complete", "complete")


def test_interrupt_maps_to_paused_stage():
    result = {"__interrupt__": [SimpleNamespace(value={"stage": "prepare"})]}
    assert derive_run_outcome(result) == ("paused_for_input", "prepare")


def test_error_message_is_bounded():
    message = safe_error_message(ValueError("x" * 2000))
    assert message.startswith("ValueError: ")
    assert len(message) == 1000


def test_retry_continues_existing_checkpoint_without_restarting():
    graph = FakeGraph(checkpoint_exists=True)
    result, restarted = invoke_pipeline(
        graph,
        "retry",
        None,
        {"configurable": {"thread_id": "session-1"}},
        recovery_input={"rough_prompt": "saved request"},
    )
    assert result == {"received": None}
    assert restarted is False
    assert graph.inputs == [None]


def test_retry_without_checkpoint_restarts_from_saved_input():
    graph = FakeGraph(checkpoint_exists=False)
    saved = {"session_id": "session-2", "rough_prompt": "saved request"}
    result, restarted = invoke_pipeline(
        graph,
        "retry",
        None,
        {"configurable": {"thread_id": "session-2"}},
        recovery_input=saved,
    )
    assert result == {"received": saved}
    assert restarted is True
    assert graph.inputs == [None, saved]


def test_legacy_retry_without_checkpoint_has_clear_recovery_message():
    graph = FakeGraph(checkpoint_exists=False)
    with pytest.raises(RecoveryInputMissingError, match="Start a new analysis"):
        invoke_pipeline(
            graph,
            "retry",
            None,
            {"configurable": {"thread_id": "legacy-session"}},
            recovery_input=None,
        )
