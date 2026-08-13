CREATE TABLE IF NOT EXISTS agent_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    scope_key TEXT NOT NULL,
    manager_name TEXT NOT NULL,
    specialist_name TEXT NOT NULL,
    stage TEXT NOT NULL,
    error_fingerprint VARCHAR(64) NOT NULL,
    error_summary TEXT NOT NULL,
    guidance TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'active', 'retired')),
    occurrence_count INT NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    success_count INT NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_agent_memory_signature UNIQUE (scope_key, specialist_name, stage, error_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_recall
    ON agent_memories(scope_key, specialist_name, stage, status, success_count DESC, updated_at DESC);
