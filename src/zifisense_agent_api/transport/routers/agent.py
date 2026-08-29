from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import AgentInvokeRequest, AgentInvokeResponse

router = APIRouter(prefix="/api/v1", tags=["Agent"])


@router.post(
    "/agent/invoke",
    response_model=AgentInvokeResponse,
    operation_id="invokeAgent",
)
def invoke_agent(
    payload: AgentInvokeRequest,
    request: Request,
    identity: Annotated[
        ClientIdentity,
        Depends(require_client("agent:invoke", agent_bucket=True)),
    ],
) -> AgentInvokeResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.agent_facade.invoke(
        request=payload,
        client_id=identity.client_id,
        request_id=request_id,
        trace_id=trace_id,
    )
