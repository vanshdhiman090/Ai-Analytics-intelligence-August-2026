"""Read-only data-source endpoints for the Google Intelligence Connector Pack."""

from __future__ import annotations

import uuid
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import require_api_key
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Dataset
from app.services.google_connectors import (
    MAX_SNAPSHOT_ROWS,
    ConnectorError,
    ConnectorRequestError,
    default_registry,
)
from app.services.tabular import json_value, profile_dataset, load_dataframe


router = APIRouter(prefix="/connectors", tags=["data connectors"], dependencies=[Depends(require_api_key)])


class ConnectorRequest(BaseModel):
    connector: Literal["google_drive", "google_sheets", "ga4", "search_console", "bigquery"]
    file_id: str | None = Field(default=None, max_length=300)
    spreadsheet_id: str | None = Field(default=None, max_length=300)
    range: str | None = Field(default=None, max_length=300)
    property_id: str | None = Field(default=None, max_length=100)
    site_url: str | None = Field(default=None, max_length=2_000)
    project_id: str | None = Field(default=None, max_length=300)
    query: str | None = Field(default=None, max_length=20_000)
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    dimensions: list[str] | None = Field(default=None, max_length=10)
    metrics: list[str] | None = Field(default=None, max_length=12)
    limit: int = Field(default=10_000, ge=1, le=MAX_SNAPSHOT_ROWS)


def _request_payload(req: ConnectorRequest) -> dict:
    return req.model_dump(exclude_none=True)


def _require_connector_access() -> None:
    if settings.RECRUITER_DEMO_MODE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "External data connectors are not available in recruiter demo mode.",
        )


def _read(req: ConnectorRequest):
    try:
        return default_registry().read(req.connector, _request_payload(req))
    except ConnectorRequestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(exc)) from exc


def _response(result, preview_limit: int = 20) -> dict:
    return {
        "connector": result.connector,
        "source_label": result.source_label,
        "source_uri": result.source_uri,
        "retrieved_at": result.retrieved_at,
        "columns": list(result.columns),
        "row_count": result.row_count,
        "preview": result.preview(preview_limit),
        "lineage": dict(result.request_summary),
        "read_only": True,
    }


@router.get("/catalog")
def connector_catalog():
    """Return the data-only source catalogue and setup readiness."""
    _require_connector_access()
    return {"read_only": True, "sources": default_registry().catalog()}


@router.post("/preview")
def preview_connector(req: ConnectorRequest):
    """Read a bounded source preview without creating a dataset."""
    _require_connector_access()
    return _response(_read(req))


@router.post("/snapshot", status_code=status.HTTP_201_CREATED)
def snapshot_connector(req: ConnectorRequest):
    """Read a bounded source result and save it as a normal analysis dataset."""
    _require_connector_access()
    result = _read(req)
    frame = pd.DataFrame(list(result.rows), columns=list(result.columns))
    if frame.empty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The connector returned no rows to analyze.")
    path = settings.DATA_DIR / "uploads" / f"connector-{uuid.uuid4()}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    db = SessionLocal()
    try:
        profile = profile_dataset(path)
        profile["source_lineage"] = {
            "connector": result.connector,
            "source_uri": result.source_uri,
            "retrieved_at": result.retrieved_at,
            "request": dict(result.request_summary),
            "read_only": True,
        }
        dataset = Dataset(
            file_path=str(path),
            original_filename=result.source_label,
            content_type="application/connector-snapshot+csv",
            size_bytes=path.stat().st_size,
            sha256=__import__("hashlib").sha256(path.read_bytes()).hexdigest(),
            schema_profile=profile,
            row_count=profile["row_count"],
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        loaded = load_dataframe(path).head(20)
        return {
            "dataset_id": str(dataset.id),
            "filename": dataset.original_filename,
            "size_bytes": dataset.size_bytes,
            "profile": profile,
            "preview": [{str(column): json_value(value) for column, value in row.items()} for row in loaded.to_dict(orient="records")],
            "connector": result.connector,
            "source_uri": result.source_uri,
            "retrieved_at": result.retrieved_at,
            "read_only": True,
        }
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        db.close()
