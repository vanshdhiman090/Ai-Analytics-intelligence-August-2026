-- AI Analytics Workspace — Database Schema v1
-- Matches Master Plan Section 6.1

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    business_task TEXT,
    current_stage TEXT NOT NULL DEFAULT 'ask'
        CHECK (current_stage IN ('ask','prepare','process','analyze','share','act','complete')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','paused_for_input','complete','error')),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    original_filename TEXT,
    schema_profile JSONB,
    row_count INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    action_type TEXT NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    code_executed TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('chart','report','summary')),
    file_path TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_datasets_session ON datasets(session_id);
CREATE INDEX idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX idx_agent_actions_session ON agent_actions(session_id);
CREATE INDEX idx_artifacts_session ON artifacts(session_id);
