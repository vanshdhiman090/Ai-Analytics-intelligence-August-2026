"""Small, explicit database transitions shared by workflow nodes."""

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel


def mark_stage(session_id: str, stage: str) -> None:
    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            raise RuntimeError("Session no longer exists")
        session.current_stage = stage
        session.status = "running"
        session.updated_at = func.now()
        db.commit()
    finally:
        db.close()
