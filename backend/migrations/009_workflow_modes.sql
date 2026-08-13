-- User-selected pace is durable so a resumed run follows the same approvals.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS workflow_mode TEXT NOT NULL DEFAULT 'fast';
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_workflow_mode_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_workflow_mode_check CHECK (workflow_mode IN ('fast', 'professional'));
