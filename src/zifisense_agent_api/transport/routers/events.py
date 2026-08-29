from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import (
    EventIngestResponse,
    FieldMeasurementCompletedEventRequest,
)

router = APIRouter(prefix="/api/v1", tags=["Events"])


@router.post("/events", response_model=EventIngestResponse, operation_id="ingestEvent")
def ingest_event(
    payload: FieldMeasurementCompletedEventRequest,
    request: Request,
    identity: Annotated[ClientIdentity, Depends(require_client("event:write"))],
) -> EventIngestResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.event_service.ingest_field_measurement(
        request=payload,
        client_id=identity.client_id,
        request_id=request_id,
        trace_id=trace_id,
    )
