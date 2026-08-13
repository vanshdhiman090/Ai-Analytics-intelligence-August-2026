from copy import deepcopy

import pytest

from app.agent.subagents.base import BaseSubAgent
from app.agent.subagents.data_specialists import (
    CleaningSpecialist,
    DataIntakeSpecialist,
    DataQualitySpecialist,
    DataSpecialistContractError,
    PrivacyBiasSpecialist,
    SchemaSpecialist,
)


def schema_profile():
    return {
        "row_count": 3,
        "column_count": 3,
        "duplicate_row_count": 0,
        "all_null_columns": [],
        "constant_columns": [],
        "columns": {
            "order_id": {"semantic_type": "categorical", "null_count": 0, "unique_count": 3},
            "region": {"semantic_type": "categorical", "null_count": 0, "unique_count": 2},
            "sales": {"semantic_type": "numeric", "null_count": 0, "unique_count": 3},
        },
    }


def complete_state():
    return {
        "file_path": "input/sales.csv",
        "original_filename": "sales.csv",
        "source_sha256": "abc123",
        "source_register": [
            {"source_id": "S1", "filename": "sales.csv", "format": "CSV", "sha256": "abc123"}
        ],
        "schema_profile": schema_profile(),
        "integrity_checks": [{"check_id": "IC1", "check": "Unique columns", "status": "Pass"}],
        "quality_findings": [{"column": "region", "issue": "Review category spelling", "severity": "low"}],
        "validation_status": "Pass",
        "cleaned_path": "runs/session/cleaned.csv",
        "final_summary": {"rows_before": 4, "rows_after": 3, "rows_removed": 1},
        "cleaning_checklist": {
            "meaning_changing_imputation_performed": False,
            "transformations": ["Removed one exact duplicate"],
        },
        "cleaning_log": [{"log_id": "CL1", "action": "Remove exact duplicate"}],
        "roccc_answers": {
            "source_license": "Approved internal source",
            "privacy_restrictions": "Internal aggregate analysis only",
        },
    }


@pytest.mark.parametrize(
    ("specialist", "result_key"),
    [
        (DataIntakeSpecialist(), "data_intake_review"),
        (SchemaSpecialist(), "schema_review"),
        (DataQualitySpecialist(), "data_quality_review"),
        (CleaningSpecialist(), "cleaning_review"),
        (PrivacyBiasSpecialist(), "privacy_bias_review"),
    ],
)
def test_specialists_are_additive_deterministic_reviewers(specialist, result_key):
    state = complete_state()
    original = deepcopy(state)

    first = specialist.execute(state)
    second = specialist.execute(state)

    assert isinstance(specialist, BaseSubAgent)
    assert first == second
    assert list(first) == [result_key]
    assert first[result_key]["specialist"] == specialist.name
    assert first[result_key]["role"] == specialist.domain_role
    assert first[result_key]["checks"]
    assert state == original


@pytest.mark.parametrize(
    "specialist_type",
    [DataIntakeSpecialist, SchemaSpecialist, DataQualitySpecialist, CleaningSpecialist, PrivacyBiasSpecialist],
)
def test_every_specialist_has_professional_role_metadata(specialist_type):
    metadata = specialist_type.professional_metadata()

    assert metadata["name"] == specialist_type.name
    assert metadata["role"] == specialist_type.domain_role
    assert metadata["mission"]
    assert metadata["responsibilities"]
    assert metadata["required_inputs"]
    assert metadata["outputs"]
    assert metadata["quality_gates"]
    assert metadata["allowed_actions"] == [
        "Read workflow state",
        "Perform deterministic contract checks",
        "Return an additive review payload",
    ]
    assert metadata["escalation_conditions"]


def test_data_intake_rejects_duplicate_source_identity():
    state = complete_state()
    state["source_register"].append(
        {"source_id": "S1", "filename": "other.csv", "format": "CSV"}
    )

    with pytest.raises(DataSpecialistContractError, match="duplicate source identifiers: S1"):
        DataIntakeSpecialist().execute(state)


def test_schema_rejects_profile_count_mismatch():
    state = complete_state()
    state["schema_profile"]["column_count"] = 4

    with pytest.raises(DataSpecialistContractError, match="declares 4, but 3"):
        SchemaSpecialist().execute(state)


def test_schema_only_labels_key_as_candidate():
    review = SchemaSpecialist().execute(complete_state())["schema_review"]

    assert review["candidate_keys"] == ["order_id"]
    assert "confirmation" in review["candidate_key_caveat"]
    assert review["grain_status"].startswith("Unverified")


def test_data_quality_blocks_failed_integrity_evidence():
    state = complete_state()
    state["validation_status"] = "Fail"
    state["integrity_checks"] = [{"check_id": "IC9", "status": "Fail"}]

    with pytest.raises(DataSpecialistContractError, match="failed integrity checks: IC9"):
        DataQualitySpecialist().execute(state)


def test_data_quality_rejects_pass_that_hides_warning():
    state = complete_state()
    state["integrity_checks"] = [{"check_id": "IC2", "status": "Warning"}]

    with pytest.raises(DataSpecialistContractError, match="Pass despite warning"):
        DataQualitySpecialist().execute(state)


def test_cleaning_rejects_unreconciled_rows_and_meaning_changing_imputation():
    state = complete_state()
    state["final_summary"]["rows_removed"] = 0
    with pytest.raises(DataSpecialistContractError, match="unreconciled row counts"):
        CleaningSpecialist().execute(state)

    state = complete_state()
    state["cleaning_checklist"]["meaning_changing_imputation_performed"] = True
    with pytest.raises(DataSpecialistContractError, match="meaning-changing imputation"):
        CleaningSpecialist().execute(state)


def test_privacy_specialist_flags_risk_without_claiming_sensitive_data_or_clearance():
    state = complete_state()
    state["schema_profile"]["column_count"] = 4
    state["schema_profile"]["columns"]["customer_email"] = {
        "semantic_type": "text",
        "null_count": 0,
        "unique_count": 3,
    }
    state["roccc_answers"] = {}

    review = PrivacyBiasSpecialist().execute(state)["privacy_bias_review"]

    assert review["status"] == "review_required"
    assert review["potential_sensitive_columns"] == [
        {"column": "customer_email", "matched_risk_tokens": ["email"]}
    ]
    assert review["fairness_status"] == "No fairness conclusion made."
    assert review["legal_clearance"].startswith("Not provided")


def test_privacy_specialist_preserves_explicit_restriction():
    state = complete_state()
    state["roccc_answers"]["privacy_restrictions"] = "Do not distribute externally"

    review = PrivacyBiasSpecialist().execute(state)["privacy_bias_review"]

    assert review["status"] == "restricted"
    assert review["escalation_required"] is True
