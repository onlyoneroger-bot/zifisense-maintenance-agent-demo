from __future__ import annotations

import threading
import uuid
from datetime import datetime

from zifisense_agent_api.adapters.fixtures import FixtureCatalog
from zifisense_agent_api.domain.entities import EvaluationBundle
from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.domain.task_state import TaskState
from zifisense_agent_api.infrastructure.idempotency import canonical_request_hash
from zifisense_agent_api.infrastructure.repositories import (
    EvaluationRepository,
    decode_idempotent_response,
)
from zifisense_agent_api.transport.schemas import (
    CreateEvaluationSessionData,
    CreateEvaluationSessionRequest,
    CreateEvaluationSessionResponse,
    ResponseMeta,
)


class EvaluationService:
    def __init__(self, repository: EvaluationRepository, fixtures: FixtureCatalog) -> None:
        self._repository = repository
        self._fixtures = fixtures
        self._write_lock = threading.Lock()

    def create(
        self,
        *,
        request: CreateEvaluationSessionRequest,
        client_id: str,
        idempotency_key: str,
        request_id: str,
        trace_id: str,
    ) -> CreateEvaluationSessionResponse:
        request_hash = canonical_request_hash(request.model_dump(mode="json"))
        with self._write_lock:
            existing = self._repository.find_idempotency(
                client_id, "create_evaluation_session", idempotency_key
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise ApplicationError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency key was already used with a different request body.",
                    )
                return CreateEvaluationSessionResponse.model_validate(
                    decode_idempotent_response(existing)
                )

            try:
                fixture = self._fixtures.load_alarm_scenario(request.scenario_id)
            except (KeyError, FileNotFoundError) as exc:
                raise ApplicationError(
                    400,
                    "INVALID_REQUEST",
                    "Unsupported or unavailable scenario_id.",
                    details={"scenario_id": request.scenario_id},
                ) from exc

            suffix = uuid.uuid4().hex
            bundle = EvaluationBundle(
                evaluation_session_id=f"eval_{suffix}",
                conversation_id=f"conv_{uuid.uuid4().hex}",
                task_id=f"task_{uuid.uuid4().hex}",
                scenario_id=fixture.scenario_id,
                task_state=TaskState.ALARM_RECEIVED,
            )
            response = CreateEvaluationSessionResponse(
                request_id=request_id,
                trace_id=trace_id,
                data=CreateEvaluationSessionData(
                    evaluation_session_id=bundle.evaluation_session_id,
                    conversation_id=bundle.conversation_id,
                    task_id=bundle.task_id,
                    scenario_id=bundle.scenario_id,
                    task_state=bundle.task_state,
                    scenario_summary=fixture.scenario_description,
                    suggested_questions=list(fixture.suggested_questions),
                ),
                meta=ResponseMeta(
                    timestamp=datetime.now().astimezone(),
                    is_degraded=False,
                ),
            )
            self._repository.create_evaluation(
                bundle=bundle,
                client_id=client_id,
                locale=request.locale,
                fixture=fixture,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status_code=201,
                response_json=response.model_dump_json(),
            )
            return response
