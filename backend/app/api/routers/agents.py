"""Read-only transparency endpoints for the managed specialist workforce."""

from fastapi import APIRouter, Depends

from app.agent.hierarchy import hierarchy_catalogue
from app.api.auth import require_api_key
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import AgentMemory

router = APIRouter(prefix="/agent", tags=["agent workforce"], dependencies=[Depends(require_api_key)])


@router.get("/hierarchy")
def get_hierarchy():
    return hierarchy_catalogue()


@router.get("/memory")
def get_learning_memory():
    """Expose bounded, sanitized lessons so operators can audit what is reused."""
    db = SessionLocal()
    try:
        rows = (
            db.query(AgentMemory)
            .filter(AgentMemory.scope_key == settings.MEMORY_SCOPE)
            .order_by(AgentMemory.updated_at.desc())
            .limit(100)
            .all()
        )
        return {
            "scope": settings.MEMORY_SCOPE,
            "items": [
                {
                    "id": str(row.id),
                    "manager": row.manager_name,
                    "specialist": row.specialist_name,
                    "stage": row.stage,
                    "error_summary": row.error_summary,
                    "guidance": row.guidance,
                    "status": row.status,
                    "occurrences": row.occurrence_count,
                    "successful_recoveries": row.success_count,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ],
        }
    finally:
        db.close()
