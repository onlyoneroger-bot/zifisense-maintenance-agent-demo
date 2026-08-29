from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import ResetRequest, ResetResponse

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


@router.post("/reset", response_model=ResetResponse, operation_id="resetDemoData")
def reset_demo_data(
    payload: ResetRequest,
    request: Request,
    _idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
    identity: Annotated[ClientIdentity, Depends(require_client("admin:write"))],
) -> ResetResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.reset_service.reset(
        payload=payload,
        client_id=identity.client_id,
        request_id=request_id,
        trace_id=trace_id,
    )
