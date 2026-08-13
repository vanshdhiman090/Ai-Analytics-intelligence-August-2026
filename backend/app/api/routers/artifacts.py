"""Artifacts router — serve files, editable document editor, DOCX/PDF download."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal

from app.api.auth import require_api_key
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Artifact, AgentAction, Checkpoint, Dataset, DocumentRevision
from app.models.schema import Session as SessionModel
from app.services.editable_documents import build_docx, build_pdf, seed_document

router = APIRouter(tags=["artifacts"], dependencies=[Depends(require_api_key)])


# ── Request models ──────────────────────────────────────────────────────────

class EditableBlock(BaseModel):
    type: Literal["prose", "bullets", "table"] = "prose"
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=20000)
    items: list[str] = Field(default_factory=list, max_length=200)
    columns: list[str] = Field(default_factory=list, max_length=20)
    rows: list[list[str]] = Field(default_factory=list, max_length=1000)


class EditableSection(BaseModel):
    heading: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=20000)
    phase: str | None = Field(default=None, max_length=100)
    blocks: list[EditableBlock] = Field(default_factory=list, max_length=100)


class EditableDocument(BaseModel):
    schema_version: str = Field(default="2.0", max_length=20)
    document_type: str = Field(default="executive_report", max_length=100)
    title: str = Field(min_length=1, max_length=300)
    subtitle: str = Field(default="", max_length=1000)
    brand: dict[str, str] = Field(default_factory=dict)
    sections: list[EditableSection] = Field(min_length=1, max_length=30)


class SaveDocumentRequest(BaseModel):
    base_version: int = Field(ge=0)
    content: EditableDocument


# ── Helpers ─────────────────────────────────────────────────────────────────

def _editable_artifact(db, artifact_id: uuid.UUID) -> Artifact:
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if artifact is None or artifact.type not in {"report", "documentation"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Editable document not found")
    return artifact


def _editor_state(db, artifact: Artifact) -> dict:
    revision = (
        db.query(DocumentRevision)
        .filter(DocumentRevision.artifact_id == artifact.id)
        .order_by(DocumentRevision.version.desc())
        .first()
    )
    if revision is not None:
        return {
            "artifact_id": str(artifact.id),
            "version": revision.version,
            "content": revision.content,
        }
    session = (
        db.query(SessionModel).filter(SessionModel.id == artifact.session_id).first()
    )
    dataset = (
        db.query(Dataset).filter(Dataset.session_id == artifact.session_id).first()
    )
    checkpoints = (
        db.query(Checkpoint)
        .filter(Checkpoint.session_id == artifact.session_id)
        .order_by(Checkpoint.created_at)
        .all()
    )
    actions = (
        db.query(AgentAction)
        .filter(AgentAction.session_id == artifact.session_id)
        .order_by(AgentAction.created_at)
        .all()
    )
    title = (artifact.metadata_ or {}).get("title") or "Analysis document"
    return {
        "artifact_id": str(artifact.id),
        "version": 0,
        "content": seed_document(
            title,
            session,
            dataset,
            checkpoints,
            actions,
            (artifact.metadata_ or {}).get("document_type"),
        ),
    }


def _safe_filename(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-.") [:80] or "analysis-document"


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: uuid.UUID):
    db = SessionLocal()
    try:
        artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
        if artifact is None or not artifact.file_path:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
        path = Path(artifact.file_path).resolve()
        if not path.is_relative_to(settings.DATA_DIR.resolve()):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Artifact path is outside managed storage",
            )
        if not path.is_file():
            raise HTTPException(
                status.HTTP_410_GONE, "Artifact file is no longer available"
            )
        suffix = path.suffix.lower()
        media_types = {
            ".html": "text/html",
            ".zip": "application/zip",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        media_type = media_types.get(suffix)
        disposition = "attachment" if suffix in {".zip", ".pptx"} else "inline"
        return FileResponse(
            path, media_type=media_type, filename=path.name, content_disposition_type=disposition
        )
    finally:
        db.close()


@router.get("/artifacts/{artifact_id}/editor")
def get_document_editor(artifact_id: uuid.UUID):
    db = SessionLocal()
    try:
        return _editor_state(db, _editable_artifact(db, artifact_id))
    finally:
        db.close()


@router.put("/artifacts/{artifact_id}/editor")
def save_document_editor(artifact_id: uuid.UUID, body: SaveDocumentRequest):
    db = SessionLocal()
    try:
        artifact = _editable_artifact(db, artifact_id)
        latest = (
            db.query(DocumentRevision)
            .filter(DocumentRevision.artifact_id == artifact.id)
            .order_by(DocumentRevision.version.desc())
            .first()
        )
        current_version = latest.version if latest else 0
        if body.base_version != current_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This document changed elsewhere. Reload it before saving.",
            )
        next_version = current_version + 1
        content = body.content.model_dump(mode="json")
        if len(json.dumps(content, ensure_ascii=False)) > 1_000_000:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "The edited document is too large",
            )
        db.add(
            DocumentRevision(
                artifact_id=artifact.id,
                session_id=artifact.session_id,
                version=next_version,
                content=content,
            )
        )
        db.commit()
        return {"artifact_id": str(artifact.id), "version": next_version, "content": content}
    finally:
        db.close()


@router.get("/artifacts/{artifact_id}/download.docx")
def download_document_docx(artifact_id: uuid.UUID):
    db = SessionLocal()
    try:
        artifact = _editable_artifact(db, artifact_id)
        state = _editor_state(db, artifact)
        charts = (
            db.query(Artifact)
            .filter(
                Artifact.session_id == artifact.session_id, Artifact.type == "chart"
            )
            .all()
        )
        chart_paths = [Path(item.file_path).resolve() for item in charts if item.file_path]
        artifact_dir = Path(artifact.file_path).resolve().parent
        if not artifact_dir.is_relative_to(settings.DATA_DIR.resolve()):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Artifact path is outside managed storage",
            )
        output = artifact_dir / f"edit-v{state['version']}.docx"
        build_docx(
            state["content"],
            output,
            chart_paths if artifact.type == "report" else [],
        )
        filename = _safe_filename(state["content"]["title"])
        return FileResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{filename}.docx",
            content_disposition_type="attachment",
        )
    finally:
        db.close()


@router.get("/artifacts/{artifact_id}/download.pdf")
def download_document_pdf(artifact_id: uuid.UUID):
    db = SessionLocal()
    try:
        artifact = _editable_artifact(db, artifact_id)
        state = _editor_state(db, artifact)
        charts = (
            db.query(Artifact)
            .filter(
                Artifact.session_id == artifact.session_id, Artifact.type == "chart"
            )
            .all()
        )
        chart_paths = [Path(item.file_path).resolve() for item in charts if item.file_path]
        artifact_dir = Path(artifact.file_path).resolve().parent
        if not artifact_dir.is_relative_to(settings.DATA_DIR.resolve()):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Artifact path is outside managed storage",
            )
        output = artifact_dir / f"edit-v{state['version']}.pdf"
        build_pdf(
            state["content"],
            output,
            chart_paths if artifact.type == "report" else [],
        )
        filename = _safe_filename(state["content"]["title"])
        return FileResponse(
            output,
            media_type="application/pdf",
            filename=f"{filename}.pdf",
            content_disposition_type="attachment",
        )
    finally:
        db.close()
