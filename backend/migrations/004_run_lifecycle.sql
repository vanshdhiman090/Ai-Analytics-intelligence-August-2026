ALTER TABLE sessions ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS run_attempt INT NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_status_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_status_check
    CHECK (status IN ('active','queued','running','paused_for_input','complete','error'));

ALTER TABLE artifacts DROP CONSTRAINT IF EXISTS artifacts_type_check;
ALTER TABLE artifacts ADD CONSTRAINT artifacts_type_check
    CHECK (type IN ('chart','report','documentation','summary'));

CREATE INDEX IF NOT EXISTS idx_sessions_status_updated
    ON sessions(status, updated_at DESC);
