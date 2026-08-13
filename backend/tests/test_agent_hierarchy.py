from types import SimpleNamespace

import pytest

from app.agent.hierarchy import MANAGERS, SPECIALISTS, SPECIALIST_TO_MANAGER, hierarchy_catalogue
from app.agent.manager import AnalyticsManager
from app.agent.subagents.base import BaseSubAgent
from app.agent.subagents.root_cause_agent import RootCauseAgent


class FakeMemory:
    def __init__(self):
        self.failures = []
        self.recoveries = []

    def recall(self, specialist, stage):
        return [SimpleNamespace(error_summary="Earlier contract mismatch.", guidance="Validate required fields first.")]

    def record_failure(self, **payload):
        self.failures.append(payload)
        return "fingerprint"

    def record_recovery(self, **payload):
        self.recoveries.append(payload)


class FlakySpecialist(BaseSubAgent):
    name = "StakeholderScopeSpecialist"
    calls = 0

    def execute(self, state, **kwargs):
        self.calls += 1
        assert state["_manager_brief"]["manager"] == "DiscoveryManager"
        assert state["_learning_lessons"]
        if self.calls == 1:
            raise TimeoutError("temporary dependency timeout")
        return {"ok": True}


class InspectingSpecialist(BaseSubAgent):
    name = "StakeholderScopeSpecialist"

    def execute(self, state, **kwargs):
        assert "secret_blob" not in state
        assert set(state) <= {"session_id", "analysis_brief", "business_question", "_manager_brief", "_learning_lessons"}
        contract = state["_manager_brief"]["task_contract"]
        assert contract["context"]["specialist_name"] == self.name
        assert contract["idempotency"]["key"].startswith("specialist:")
        return {"specialist_reviews": []}


class PermanentlyInvalidSpecialist(BaseSubAgent):
    name = "StakeholderScopeSpecialist"
    calls = 0

    def execute(self, state, **kwargs):
        self.calls += 1
        raise ValueError("required bounded input is invalid")


def test_every_specialist_has_exactly_one_manager_and_detailed_contract():
    assert set(SPECIALISTS) == set(SPECIALIST_TO_MANAGER)
    assert set(SPECIALIST_TO_MANAGER.values()) == set(MANAGERS)
    for profile in SPECIALISTS.values():
        assert profile.responsibilities
        assert profile.required_inputs
        assert profile.outputs
        assert profile.quality_gates
        assert profile.escalation_conditions


def test_catalogue_is_json_ready_and_complete():
    catalogue = hierarchy_catalogue()
    assert catalogue["chief_manager"]["name"] == "AnalyticsManager"
    assert len(catalogue["managers"]) == 5
    assert len(catalogue["specialists"]) == 24


def test_every_declared_specialist_has_a_runtime_implementation():
    manager = AnalyticsManager(memory_store=FakeMemory())
    assert set(manager.specialist_registry) == set(SPECIALISTS)
    assert "DataManager" in manager.domain_managers
    assert "QualityManager" in manager.domain_managers


def test_root_cause_runtime_identity_is_registered():
    specialist = RootCauseAgent()
    assert specialist.name == "RootCauseAgent"
    assert SPECIALIST_TO_MANAGER[specialist.name] == "AnalysisManager"


def test_manager_promotes_a_failure_only_after_success(monkeypatch):
    memory = FakeMemory()
    manager = AnalyticsManager(memory_store=memory)
    specialist = FlakySpecialist()
    specialist.calls = 0
    monkeypatch.setattr(manager, "_log_supervision", lambda *args, **kwargs: None)

    original = {"session_id": "session-1", "rough_prompt": "question"}
    result = manager.run_subagent_with_healing(specialist, original, "ask", max_retries=2)

    assert result == {"ok": True}
    assert len(memory.failures) == 1
    assert memory.recoveries == [
        {"specialist": "StakeholderScopeSpecialist", "stage": "ask", "fingerprint": "fingerprint", "attempt": 2}
    ]
    assert "_learning_lessons" not in original


def test_manager_exposes_only_allow_listed_inputs_and_a_typed_task(monkeypatch):
    manager = AnalyticsManager(memory_store=FakeMemory())
    monkeypatch.setattr(manager, "_log_supervision", lambda *args, **kwargs: None)
    result = manager.run_subagent_with_healing(
        InspectingSpecialist(),
        {
            "session_id": "session-2",
            "analysis_brief": {"objective": "Review scope"},
            "business_question": "What changed?",
            "secret_blob": "must never be delegated",
        },
        "ask",
        expected_outputs=("specialist_reviews",),
    )
    assert result == {"specialist_reviews": []}


def test_manager_does_not_retry_permanent_contract_failures(monkeypatch):
    manager = AnalyticsManager(memory_store=FakeMemory())
    specialist = PermanentlyInvalidSpecialist()
    specialist.calls = 0
    monkeypatch.setattr(manager, "_log_supervision", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="bounded input"):
        manager.run_subagent_with_healing(
            specialist, {"session_id": "session-3", "analysis_brief": {}}, "ask", max_retries=3
        )
    assert specialist.calls == 1
