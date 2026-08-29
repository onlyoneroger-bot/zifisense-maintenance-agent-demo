from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import (
    AgentSummary,
    CapabilitiesData,
    CapabilitiesResponse,
    CreateEvaluationSessionRequest,
    CreateEvaluationSessionResponse,
    ResponseMeta,
    ScenarioSummary,
)

router = APIRouter(prefix="/api/v1", tags=["Evaluation"])


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    operation_id="getCapabilities",
)
def get_capabilities(
    request: Request,
    _identity: Annotated[ClientIdentity, Depends(require_client("capability:read"))],
) -> CapabilitiesResponse:
    fixture = request.app.state.fixtures.load_alarm_scenario("reducer_gear_alarm_v1")
    request_id, trace_id = get_request_ids(request)
    return CapabilitiesResponse(
        request_id=request_id,
        trace_id=trace_id,
        data=CapabilitiesData(
            agent=AgentSummary(
                name="zifisense-intelligent-maintenance-agent",
                version=request.app.state.settings.app_version,
                locale="zh-CN",
            ),
            scenarios=[
                ScenarioSummary(
                    scenario_id=fixture.scenario_id,
                    name=fixture.scenario_name,
                    description=fixture.scenario_description,
                    suggested_questions=list(fixture.suggested_questions),
                )
            ],
            capabilities=[],
            supported_event_types=[],
            safety_boundaries=[
                "Sprint 1 currently provides isolated sessions and a Fixture-based "
                "degraded response only.",
                "RAG, industrial tools, events, task inspection, and approvals are "
                "not yet available.",
                "External industrial systems will be connected through explicitly "
                "simulated adapters.",
                "LLM does not diagnose raw high-frequency time-series data.",
                "Production-control actions are not exposed.",
                "Formal work-order submission requires explicit approval.",
            ],
        ),
        meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
    )


@router.post(
    "/evaluation/sessions",
    response_model=CreateEvaluationSessionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEvaluationSession",
)
def create_evaluation_session(
    payload: CreateEvaluationSessionRequest,
    request: Request,
    identity: Annotated[ClientIdentity, Depends(require_client("evaluation:create"))],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> CreateEvaluationSessionResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.evaluation_service.create(
        request=payload,
        client_id=identity.client_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        trace_id=trace_id,
    )
