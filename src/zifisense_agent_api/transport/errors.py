from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.transport.schemas import ErrorBody, ErrorResponse


def _request_ids(request: Request) -> tuple[str, str]:
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex}")
    trace_id = getattr(request.state, "trace_id", f"trace_{uuid.uuid4().hex}")
    return request_id, trace_id


def error_response(request: Request, error: ApplicationError) -> JSONResponse:
    request_id, trace_id = _request_ids(request)
    body = ErrorResponse(
        request_id=request_id,
        trace_id=trace_id,
        error=ErrorBody(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
        ),
    )
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(mode="json", exclude_none=True),
    )


async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    return error_response(request, exc)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = {
        "validation_errors": [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
    }
    return error_response(
        request,
        ApplicationError(
            400,
            "INVALID_REQUEST",
            "The request does not satisfy the API contract.",
            details=details,
        ),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        error = ApplicationError(404, "RESOURCE_NOT_FOUND", "The requested route was not found.")
    else:
        error = ApplicationError(
            exc.status_code,
            "INVALID_REQUEST",
            str(exc.detail),
        )
    return error_response(request, error)
