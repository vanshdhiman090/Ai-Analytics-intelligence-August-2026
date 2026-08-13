CREATE TABLE IF NOT EXISTS document_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    version INT NOT NULL CHECK (version > 0),
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_document_revision_version UNIQUE (artifact_id, version)
);

CREATE INDEX IF NOT EXISTS idx_document_revisions_artifact
    ON document_revisions(artifact_id, version DESC);
