"""Stable synchronous V1 API for governed KPI investigations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.api.auth import GuestPrincipal, require_api_key, require_guest_principal
from app.api.rca_contracts import (
    RCAErrorBodyV1,
    RCAErrorFieldV1,
    RCAErrorResponseV1,
    RCAInvestigationRequestV1,
    RCAInvestigationResponseV1,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.schema import Dataset
from app.services.rca_api import (
    RCAAPIServiceError,
    execute_rca_request,
    load_governed_dataset,
)
from app.services.dataset_lifecycle import dataset_in_use
from app.services.datasets import owned_dataset_query


logger = logging.getLogger(__name__)
DatasetRecordResolver = Callable[[UUID], Any]


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    fields: tuple[tuple[str, str], ...] = (),
) -> JSONResponse:
    payload = RCAErrorResponseV1(
        error=RCAErrorBodyV1(
            code=code,
            message=message,
            request_id=_request_id(request),
            fields=tuple(
                RCAErrorFieldV1(field=field, code=field_code)
                for field, field_code in fields
            ),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


class RCAAPIRoute(APIRoute):
    """Normalize errors only for this versioned RCA surface."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                fields = tuple(
                    (
                        ".".join(str(item) for item in error.get("loc", ()) if item != "body")
                        or "body",
                        str(error.get("type") or "invalid"),
                    )
                    for error in exc.errors()
                )
                return _error_response(
                    request,
                    status_code=422,
                    code="invalid_request",
                    message="The RCA request is invalid.",
                    fields=fields,
                )
            except RCAAPIServiceError as exc:
                return _error_response(
                    request,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.safe_message,
                    fields=exc.fields,
                )
            except HTTPException as exc:
                if exc.status_code == 401:
                    return _error_response(
                        request,
                        status_code=401,
                        code="authentication_required",
                        message="A valid API key is required.",
                    )
                logger.warning(
                    "RCA request rejected request_id=%s status=%s",
                    _request_id(request),
                    exc.status_code,
                )
                return _error_response(
                    request,
                    status_code=exc.status_code,
                    code="invalid_request",
                    message="The RCA request could not be processed.",
                )
            except Exception:
                logger.exception(
                    "RCA request failed request_id=%s", _request_id(request)
                )
                return _error_response(
                    request,
                    status_code=500,
                    code="investigation_failed",
                    message="The RCA investigation could not be completed.",
                )

        return handler


router = APIRouter(
    prefix="/v1/rca",
    tags=["rca-v1"],
    dependencies=[Depends(require_api_key)],
    route_class=RCAAPIRoute,
)


def get_rca_dataset_resolver(
    db: Session = Depends(get_db),
    guest: GuestPrincipal = Depends(require_guest_principal),
) -> DatasetRecordResolver:
    """Return a request-scoped lookup that can be replaced in HTTP tests."""

    def resolve(dataset_id: UUID) -> Dataset:
        dataset = owned_dataset_query(db, guest).filter(Dataset.id == dataset_id).first()
        if dataset is None:
            raise RCAAPIServiceError(
                status_code=404,
                code="dataset_not_found",
                message="The requested dataset was not found.",
            )
        return dataset

    return resolve


@router.post(
    "/investigations",
    response_model=RCAInvestigationResponseV1,
    responses={
        401: {"model": RCAErrorResponseV1},
        404: {"model": RCAErrorResponseV1},
        409: {"model": RCAErrorResponseV1},
        422: {"model": RCAErrorResponseV1},
        500: {"model": RCAErrorResponseV1},
    },
)
def create_rca_investigation(
    body: RCAInvestigationRequestV1,
    request: Request,
    resolve_dataset: DatasetRecordResolver = Depends(get_rca_dataset_resolver),
) -> RCAInvestigationResponseV1:
    with dataset_in_use(body.dataset_id):
        dataset = resolve_dataset(body.dataset_id)
        frame = load_governed_dataset(dataset, settings.DATA_DIR)
        return execute_rca_request(frame, body)
