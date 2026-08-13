"""Datasets router — upload, inspect, and delete datasets."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.auth import require_api_key
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Dataset
from app.services.data_model import DataModelError, ModelSource, inspect_data_model
from app.services.datasets import DatasetUploadError, store_upload
from app.services.tabular import json_value, load_dataframe, profile_dataset
from pydantic import BaseModel, Field
from app.services.sql_sources import SqlSourceError, snapshot_sql_query

router = APIRouter(tags=["datasets"], dependencies=[Depends(require_api_key)])


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
async def upload_dataset(file: UploadFile = File(...)):
    try:
        stored = await store_upload(file, settings.DATA_DIR, settings.MAX_UPLOAD_BYTES)
    except DatasetUploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    profile = profile_dataset(stored.path)
    frame = load_dataframe(stored.path)
    preview = [
        {str(column): json_value(value) for column, value in row.items()}
        for row in frame.head(8).to_dict(orient="records")
    ]
    db = SessionLocal()
    try:
        dataset = Dataset(
            file_path=str(stored.path),
            original_filename=stored.original_filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            schema_profile=profile,
            row_count=profile["row_count"],
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        return {
            "dataset_id": str(dataset.id),
            "filename": dataset.original_filename,
            "size_bytes": dataset.size_bytes,
            "profile": profile,
            "preview": preview,
        }
    except Exception:
        Path(stored.path).unlink(missing_ok=True)
        raise
    finally:
        db.close()


@router.post("/datasets/sql", status_code=status.HTTP_201_CREATED)
def import_sql_dataset(req: SqlSourceRequest):
    """Create a local CSV snapshot from a one-time, read-only SQL query."""
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
