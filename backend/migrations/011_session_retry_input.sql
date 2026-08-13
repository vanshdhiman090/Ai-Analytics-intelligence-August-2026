-- Preserve the sanitized workflow start envelope so a run that fails before
-- its first LangGraph checkpoint can be restarted safely.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS run_input JSONB;
