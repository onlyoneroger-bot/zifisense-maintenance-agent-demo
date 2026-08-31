from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    TaskSnapshotResponse,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


@router.get("/{task_id}", response_model=TaskSnapshotResponse, operation_id="getTask")
def get_task(
    task_id: str,
    request: Request,
    identity: Annotated[ClientIdentity, Depends(require_client("task:read"))],
) -> TaskSnapshotResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.task_service.get_snapshot(
        task_id=task_id,
        client_id=identity.client_id,
        request_id=request_id,
        trace_id=trace_id,
    )


@router.post(
    "/{task_id}/approvals",
    response_model=ApprovalDecisionResponse,
    operation_id="decideApproval",
)
def decide_approval(
    task_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
    _idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    identity: Annotated[ClientIdentity, Depends(require_client("approval:write"))],
) -> ApprovalDecisionResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.approval_service.decide(
        task_id=task_id,
        request=payload,
        client_id=identity.client_id,
        request_id=request_id,
        trace_id=trace_id,
    )
