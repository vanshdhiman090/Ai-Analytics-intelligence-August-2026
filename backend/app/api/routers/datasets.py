"""Datasets router — upload, inspect, and delete datasets."""

from __future__ import annotations

import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.auth import require_api_key
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Dataset
from app.services.data_model import DataModelError, ModelSource, inspect_data_model
from app.services.datasets import (
    DatasetProcessingError,
    DatasetRegistrationError,
    DatasetTooLargeError,
    DatasetUploadError,
    register_stored_dataset,
    store_upload,
)
from app.services.tabular import json_value, load_dataframe, profile_dataset
from pydantic import BaseModel, Field
from app.services.sql_sources import SqlSourceError, snapshot_sql_query

router = APIRouter(tags=["datasets"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger(__name__)


def _upload_error(
    request: Request, *, status_code: int, code: str, message: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(getattr(request.state, "request_id", "unknown")),
                "fields": [],
            }
        },
    )


class DataModelRequest(BaseModel):
    dataset_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)


class SqlSourceRequest(BaseModel):
    connection_url: str = Field(min_length=12, max_length=4000)
    query: str = Field(min_length=8, max_length=20_000)
    label: str = Field(default="SQL query result", min_length=2, max_length=120)


def model_sources(datasets: list[Dataset]) -> list[ModelSource]:
    return [
        ModelSource(
            dataset_id=str(item.id),
            filename=item.original_filename or Path(item.file_path).name,
            path=Path(item.file_path),
            sha256=item.sha256,
        )
        for item in datasets
    ]


@router.post("/datasets", status_code=status.HTTP_201_CREATED)
async def upload_dataset(request: Request, file: UploadFile = File(...)):
    if settings.RECRUITER_DEMO_MODE:
        await file.close()
        return _upload_error(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="external_dataset_ingestion_disabled",
            message="External dataset upload is not available in recruiter demo mode.",
        )
    try:
        stored = await store_upload(file, settings.DATA_DIR, settings.MAX_UPLOAD_BYTES)
    except DatasetTooLargeError as exc:
        return _upload_error(
            request,
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="dataset_too_large",
            message=str(exc),
        )
    except DatasetUploadError as exc:
        return _upload_error(
            request,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_dataset",
            message=str(exc),
        )

    db = SessionLocal()
    try:
        return register_stored_dataset(stored, db)
    except (DatasetProcessingError, DatasetRegistrationError) as exc:
        Path(stored.path).unlink(missing_ok=True)
        logger.exception(
            "Dataset preparation failed request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        return _upload_error(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=(
                "dataset_processing_failed"
                if isinstance(exc, DatasetProcessingError)
                else "dataset_registration_failed"
            ),
            message=str(exc),
        )
    finally:
        db.close()


@router.post("/datasets/sql", status_code=status.HTTP_201_CREATED)
def import_sql_dataset(req: SqlSourceRequest, request: Request):
    """Create a local CSV snapshot from a one-time, read-only SQL query."""
    if settings.RECRUITER_DEMO_MODE:
        return _upload_error(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="external_dataset_ingestion_disabled",
            message="External dataset ingestion is not available in recruiter demo mode.",
        )
    try:
        path, digest = snapshot_sql_query(req.connection_url, req.query, settings.DATA_DIR)
        profile = profile_dataset(path)
        frame = load_dataframe(path)
        preview = [{str(column): json_value(value) for column, value in row.items()} for row in frame.head(8).to_dict(orient="records")]
    except SqlSourceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db = SessionLocal()
    try:
        dataset = Dataset(file_path=str(path), original_filename=req.label, content_type="application/sql-result", size_bytes=path.stat().st_size, sha256=digest, schema_profile=profile, row_count=profile["row_count"])
        db.add(dataset); db.commit(); db.refresh(dataset)
        return {"dataset_id": str(dataset.id), "filename": dataset.original_filename, "size_bytes": dataset.size_bytes, "profile": profile, "preview": preview}
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        db.close()


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: uuid.UUID):
    """Remove an unassigned dataset and its uploaded file."""
    db = SessionLocal()
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if dataset is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
        if dataset.session_id is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Dataset is assigned to an analysis and cannot be deleted directly. Delete the session instead.",
            )
        file_path = Path(dataset.file_path)
        db.delete(dataset)
        db.commit()
        file_path.unlink(missing_ok=True)
    finally:
        db.close()


@router.post("/data-model/inspect")
def inspect_uploaded_data_model(req: DataModelRequest):
    db = SessionLocal()
    try:
        rows = db.query(Dataset).filter(Dataset.id.in_(req.dataset_ids)).all()
        by_id = {item.id: item for item in rows}
        if len(by_id) != len(set(req.dataset_ids)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more datasets were not found")
        datasets = [by_id[item] for item in req.dataset_ids]
        if any(item.session_id is not None for item in datasets):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "One or more datasets are already assigned to an analysis",
            )
        return inspect_data_model(model_sources(datasets))
    except DataModelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    finally:
        db.close()
