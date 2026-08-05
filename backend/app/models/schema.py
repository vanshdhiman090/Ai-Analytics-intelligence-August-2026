import uuid
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Session(Base):
    __tablename__ = "sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    business_task = Column(Text)
    current_stage = Column(Text, nullable=False, default="ask")
    status = Column(Text, nullable=False, default="active")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    file_path = Column(Text, nullable=False)
    original_filename = Column(Text)
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


class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    type = Column(Text, nullable=False)
    file_path = Column(Text)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
