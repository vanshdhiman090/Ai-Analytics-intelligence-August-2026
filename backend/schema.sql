-- AI Analytics Workspace — Database Schema v1
-- Matches Master Plan Section 6.1

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    business_task TEXT,
    current_stage TEXT NOT NULL DEFAULT 'ask'
        CHECK (current_stage IN ('ask','prepare','process','analyze','share','act','deliverables','complete')),
    workflow_mode TEXT NOT NULL DEFAULT 'fast'
        CHECK (workflow_mode IN ('fast','professional')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','queued','running','paused_for_input','complete','error')),
    run_input JSONB,
    result_summary JSONB,
    error_message TEXT,
    run_attempt INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    guest_owner_id UUID,
    file_path TEXT NOT NULL,
    original_filename TEXT,
    content_type TEXT,
    size_bytes INT,
    sha256 VARCHAR(64),
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

CREATE TABLE agent_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    scope_key TEXT NOT NULL,
    manager_name TEXT NOT NULL,
    specialist_name TEXT NOT NULL,
    stage TEXT NOT NULL,
    error_fingerprint VARCHAR(64) NOT NULL,
    error_summary TEXT NOT NULL,
    guidance TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','active','retired')),
    occurrence_count INT NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    success_count INT NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_agent_memory_signature UNIQUE (scope_key, specialist_name, stage, error_fingerprint)
);

CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('chart','report','documentation','summary','presentation','project_files')),
    file_path TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE document_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    version INT NOT NULL CHECK (version > 0),
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_document_revision_version UNIQUE (artifact_id, version)
);

CREATE INDEX idx_datasets_session ON datasets(session_id);
CREATE INDEX idx_datasets_guest_owner ON datasets(guest_owner_id);
CREATE INDEX idx_datasets_sha256 ON datasets(sha256);
CREATE INDEX idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX idx_agent_actions_session ON agent_actions(session_id);
CREATE INDEX idx_agent_memories_recall ON agent_memories(scope_key, specialist_name, stage, status, success_count DESC, updated_at DESC);
CREATE INDEX idx_artifacts_session ON artifacts(session_id);
CREATE INDEX idx_document_revisions_artifact ON document_revisions(artifact_id, version DESC);
CREATE INDEX idx_sessions_status_updated ON sessions(status, updated_at DESC);
