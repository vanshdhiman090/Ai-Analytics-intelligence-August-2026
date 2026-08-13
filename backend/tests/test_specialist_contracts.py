import pytest
from pydantic import ValidationError

from app.agent.specialist_contracts import (
    ContractValue,
    Diagnostic,
    ErrorClassification,
    ErrorKind,
    IdempotencyMetadata,
    RetryDisposition,
    ReviewDecision,
    SpecialistResult,
    SpecialistTask,
    TaskContext,
    build_idempotency_key,
    classify_error,
    fingerprint_inputs,
    validate_specialist_result,
)


def task(**changes):
    payload = {
        "task_id": "task-1",
        "task_type": "profile_schema",
        "objective": "Profile the selected dataset fields without changing the source.",
        "context": TaskContext(
            session_id="session-1",
            trace_id="trace-1",
            manager_name="DataManager",
            specialist_name="SchemaSpecialist",
            stage="prepare",
        ),
        "idempotency": IdempotencyMetadata(key="session-1:schema", max_attempts=2),
        "required_inputs": ("dataset_ref",),
        "required_outputs": ("schema_profile",),
        "inputs": (ContractValue(name="dataset_ref", value="dataset://clean/1"),),
    }
    payload.update(changes)
    return SpecialistTask(**payload)


def completed_result(**changes):
    payload = {
        "result_id": "result-1",
        "task_id": "task-1",
        "specialist_name": "SchemaSpecialist",
        "status": "completed",
        "outputs": (ContractValue(name="schema_profile", value={"rows": 100}),),
    }
    payload.update(changes)
    return SpecialistResult(**payload)


def test_task_is_immutable_and_contains_only_bounded_named_inputs():
    assignment = task()

    assert assignment.input_value("dataset_ref") == "dataset://clean/1"
    with pytest.raises(ValidationError):
        assignment.objective = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SpecialistTask(**(assignment.model_dump() | {"state": {"secret": "value"}}))


def test_task_rejects_missing_input_and_full_workflow_state():
    with pytest.raises(ValidationError, match="Missing required specialist inputs"):
        task(inputs=())

    with pytest.raises(ValidationError, match="Full mutable workflow state"):
        task(
            required_inputs=("state",),
            inputs=(ContractValue(name="state", value={"all": "workflow data"}),),
        )


def test_result_must_match_task_identity_and_required_outputs():
    assignment = task()
    assert validate_specialist_result(assignment, completed_result()).result_id == "result-1"

    with pytest.raises(ValueError, match="missing required outputs"):
        validate_specialist_result(
            assignment,
            completed_result(outputs=(ContractValue(name="other", value=1),)),
        )
    with pytest.raises(ValueError, match="identity"):
        validate_specialist_result(
            assignment,
            completed_result(specialist_name="DifferentSpecialist"),
        )


def test_failed_result_requires_classified_error():
    with pytest.raises(ValidationError, match="require an error classification"):
        SpecialistResult(
            result_id="result-2",
            task_id="task-1",
            specialist_name="SchemaSpecialist",
            status="failed",
        )


def test_review_statuses_enforce_approval_revision_and_blocking_rules():
    approved = ReviewDecision(
        review_id="review-1",
        task_id="task-1",
        result_id="result-1",
        reviewer_name="QualityManager",
        status="approved",
        reasons=("All required outputs passed validation.",),
    )
    assert approved.status.value == "approved"

    with pytest.raises(ValidationError, match="must specify requested_changes"):
        ReviewDecision(
            review_id="review-2",
            task_id="task-1",
            result_id="result-1",
            reviewer_name="QualityManager",
            status="revision_required",
        )

    blocked = ReviewDecision(
        review_id="review-3",
        task_id="task-1",
        result_id="result-1",
        reviewer_name="QualityManager",
        status="blocked",
        reasons=("Required source permission is unavailable.",),
    )
    assert blocked.status.value == "blocked"


def test_diagnostics_and_classifications_redact_secrets():
    diagnostic = Diagnostic.from_exception(
        RuntimeError("password=hunter2 Authorization: Bearer abc.def token=private")
    )
    assert "hunter2" not in diagnostic.message
    assert "abc.def" not in diagnostic.message
    assert "private" not in diagnostic.message
    assert diagnostic.message.count("[REDACTED]") >= 3

    classified = classify_error(ConnectionError("postgres://admin:secret@db.example unavailable"))
    assert classified.kind == ErrorKind.TRANSIENT_DEPENDENCY
    assert classified.retry == RetryDisposition.BACKOFF
    assert "admin" not in classified.summary
    assert "secret" not in classified.summary


def test_error_classification_prevents_unsafe_retry_policies():
    with pytest.raises(ValidationError, match="must not be retried"):
        ErrorClassification(
            kind="contract_violation",
            retry="immediate",
            code="BAD_CONTRACT",
            summary="Required output is absent.",
        )

    invalid_input = classify_error(ValueError("missing metric column"))
    assert invalid_input.kind == ErrorKind.INPUT_INVALID
    assert invalid_input.retry == RetryDisposition.AFTER_INPUT


def test_idempotency_helpers_are_stable_and_do_not_expose_inputs():
    fingerprint = fingerprint_inputs({"dataset_ref": "dataset://clean/1", "token": "secret-token"})
    assert len(fingerprint) == 64
    assert fingerprint == fingerprint_inputs(
        {"token": "different-secret", "dataset_ref": "dataset://clean/1"}
    )

    key = build_idempotency_key(
        session_id="session-1",
        specialist_name="SchemaSpecialist",
        task_type="profile_schema",
        input_fingerprint=fingerprint,
    )
    assert key == build_idempotency_key(
        session_id="session-1",
        specialist_name="SchemaSpecialist",
        task_type="profile_schema",
        input_fingerprint=fingerprint,
    )
    assert "dataset" not in key


def test_attempt_cannot_exceed_manager_retry_budget():
    with pytest.raises(ValidationError, match="attempt cannot exceed max_attempts"):
        IdempotencyMetadata(key="task:key", attempt=3, max_attempts=2)
