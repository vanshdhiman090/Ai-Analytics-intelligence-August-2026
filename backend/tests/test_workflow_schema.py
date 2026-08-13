from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_session_stage_constraint_includes_deliverables_checkpoint():
    canonical_schema = (BACKEND_ROOT / "schema.sql").read_text(encoding="utf-8")
    migration = (BACKEND_ROOT / "migrations" / "010_deliverables_stage.sql").read_text(encoding="utf-8")

    assert "'deliverables'" in canonical_schema
    assert "'deliverables'" in migration
    assert "sessions_current_stage_check" in migration


def test_session_schema_persists_original_retry_input():
    canonical_schema = (BACKEND_ROOT / "schema.sql").read_text(encoding="utf-8")
    migration = (BACKEND_ROOT / "migrations" / "011_session_retry_input.sql").read_text(encoding="utf-8")

    assert "run_input JSONB" in canonical_schema
    assert "ADD COLUMN IF NOT EXISTS run_input JSONB" in migration
