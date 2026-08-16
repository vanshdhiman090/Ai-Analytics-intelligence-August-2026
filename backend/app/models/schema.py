import uuid
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Session(Base):
    __tablename__ = "sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    business_task = Column(Text)
    current_stage = Column(Text, nullable=False, default="ask")
    workflow_mode = Column(Text, nullable=False, default="fast")
    status = Column(Text, nullable=False, default="active")
    run_input = Column(JSONB)
    result_summary = Column(JSONB)
    error_message = Column(Text)
    run_attempt = Column(Integer, nullable=False, default=0)
    started_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    guest_owner_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    file_path = Column(Text, nullable=False)
    original_filename = Column(Text)
    content_type = Column(Text)
    size_bytes = Column(Integer)
    sha256 = Column(String(64))
    schema_profile = Column(JSONB)
    row_count = Column(Integer)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    stage = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    resolved_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class AgentAction(Base):
    __tablename__ = "agent_actions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    stage = Column(Text, nullable=False)
    action_type = Column(Text, nullable=False)
    input_summary = Column(Text)
    output_summary = Column(Text)
    code_executed = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint("scope_key", "specialist_name", "stage", "error_fingerprint", name="uq_agent_memory_signature"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    scope_key = Column(Text, nullable=False)
    manager_name = Column(Text, nullable=False)
    specialist_name = Column(Text, nullable=False)
    stage = Column(Text, nullable=False)
    error_fingerprint = Column(String(64), nullable=False)
    error_summary = Column(Text, nullable=False)
    guidance = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="candidate")
    occurrence_count = Column(Integer, nullable=False, default=1)
    success_count = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    type = Column(Text, nullable=False)
    file_path = Column(Text)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_document_revision_version"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(JSONB, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
