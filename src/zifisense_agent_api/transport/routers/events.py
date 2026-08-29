from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import (
    AlarmRaisedEventRequest,
    EventIngestResponse,
    FieldMeasurementCompletedEventRequest,
    WorkOrderCompletedEventRequest,
)

router = APIRouter(prefix="/api/v1", tags=["Events"])


@router.post("/events", response_model=EventIngestResponse, operation_id="ingestEvent")
def ingest_event(
    payload: Annotated[
        AlarmRaisedEventRequest
        | FieldMeasurementCompletedEventRequest
        | WorkOrderCompletedEventRequest,
        Field(discriminator="event_type"),
    ],
    request: Request,
    identity: Annotated[ClientIdentity, Depends(require_client("event:write"))],
) -> EventIngestResponse:
    request_id, trace_id = get_request_ids(request)
    if isinstance(payload, AlarmRaisedEventRequest):
        return request.app.state.event_service.ingest_alarm(
            request=payload,
            client_id=identity.client_id,
            request_id=request_id,
            trace_id=trace_id,
        )
    if isinstance(payload, FieldMeasurementCompletedEventRequest):
        return request.app.state.event_service.ingest_field_measurement(
            request=payload,
            client_id=identity.client_id,
            request_id=request_id,
            trace_id=trace_id,
        )
    return request.app.state.event_service.ingest_work_order_completion(
        request=payload,
        client_id=identity.client_id,
        request_id=request_id,
        trace_id=trace_id,
    )
