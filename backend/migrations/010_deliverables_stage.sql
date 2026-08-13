-- The workflow pauses here so the user can choose files before PackageAgent
-- creates anything. Keep the database lifecycle constraint aligned with it.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_current_stage_check;
ALTER TABLE sessions
    ADD CONSTRAINT sessions_current_stage_check
    CHECK (current_stage IN ('ask', 'prepare', 'process', 'analyze', 'share', 'act', 'deliverables', 'complete'));
