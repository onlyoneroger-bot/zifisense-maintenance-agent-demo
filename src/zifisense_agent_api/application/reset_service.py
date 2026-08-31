from __future__ import annotations

from datetime import datetime

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.schemas import (
    ResetData,
    ResetRequest,
    ResetResponse,
    ResponseMeta,
)


class ResetService:
    def __init__(self, repository: EvaluationRepository) -> None:
        self._repository = repository

    def reset(
        self,
        *,
        payload: ResetRequest,
        client_id: str,
        request_id: str,
        trace_id: str,
    ) -> ResetResponse:
        if payload.scope == "SESSION":
            if not payload.evaluation_session_id:
                raise ApplicationError(
                    400,
                    "INVALID_REQUEST",
                    "evaluation_session_id is required for SESSION reset.",
                )
            evaluation = self._repository.get_evaluation_session(payload.evaluation_session_id)
            if evaluation is None:
                raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Session does not exist.")
            if evaluation.client_id != client_id:
                raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Session access is forbidden.")
            count = self._repository.reset_evaluation_session(payload.evaluation_session_id)
        else:
            count = self._repository.reset_all_evaluation_sessions()
        return ResetResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=ResetData(scope=payload.scope, status="COMPLETED", reset_count=count),
            meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
        )
