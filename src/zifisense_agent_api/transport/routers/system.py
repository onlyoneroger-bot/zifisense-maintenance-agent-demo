from datetime import datetime

from fastapi import APIRouter, Request

from zifisense_agent_api.transport.schemas import HealthResponse

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def get_health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=request.app.state.settings.app_version,
        timestamp=datetime.now().astimezone(),
    )
