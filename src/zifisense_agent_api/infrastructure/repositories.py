from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select

from zifisense_agent_api.domain.entities import AlarmFixture, EvaluationBundle
from zifisense_agent_api.infrastructure.database import (
    AlarmEventRecord,
    ConversationRecord,
    Database,
    EvaluationSessionRecord,
    IdempotencyRecord,
    TaskRecord,
    iso_now,
)


@dataclass(frozen=True, slots=True)
class TaskContext:
    evaluation: EvaluationSessionRecord
    conversation: ConversationRecord
    task: TaskRecord
    alarm: AlarmEventRecord


class EvaluationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def find_idempotency(
        self, client_id: str, operation: str, key: str
    ) -> IdempotencyRecord | None:
        with self._database.session_factory() as session:
            return session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.client_id == client_id,
                    IdempotencyRecord.operation == operation,
                    IdempotencyRecord.idempotency_key == key,
                )
            )

    def create_evaluation(
        self,
        *,
        bundle: EvaluationBundle,
        client_id: str,
        locale: str,
        fixture: AlarmFixture,
        idempotency_key: str,
        request_hash: str,
        status_code: int,
        response_json: str,
    ) -> None:
        created_at = iso_now()
        with self._database.session_factory.begin() as session:
            session.add(
                EvaluationSessionRecord(
                    id=bundle.evaluation_session_id,
                    client_id=client_id,
                    scenario_id=bundle.scenario_id,
                    locale=locale,
                    created_at=created_at,
                )
            )
            session.add(
                ConversationRecord(
                    id=bundle.conversation_id,
                    evaluation_session_id=bundle.evaluation_session_id,
                    created_at=created_at,
                )
            )
            session.add(
                TaskRecord(
                    id=bundle.task_id,
                    evaluation_session_id=bundle.evaluation_session_id,
                    state=bundle.task_state.value,
                    asset_id=fixture.asset_id,
                    created_at=created_at,
                )
            )
            session.add(
                AlarmEventRecord(
                    alarm_id=fixture.alarm_id,
                    task_id=bundle.task_id,
                    asset_id=fixture.asset_id,
                    measurement_point_id=fixture.measurement_point_id,
                    severity=fixture.severity,
                    diagnosis_text=fixture.diagnosis_text,
                    confidence=fixture.confidence,
                    algorithm_version=fixture.algorithm_version,
                    source_system=fixture.source_system,
                    observed_at=fixture.alarm_time.isoformat(),
                    evidence_id=f"evd_{bundle.task_id.removeprefix('task_')}",
                    evidence_summary=fixture.evidence_summary,
                    is_simulated=fixture.is_simulated,
                )
            )
            session.add(
                IdempotencyRecord(
                    client_id=client_id,
                    operation="create_evaluation_session",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    status_code=status_code,
                    response_json=response_json,
                    created_at=created_at,
                )
            )

    def get_task_context(
        self,
        evaluation_session_id: str,
        conversation_id: str,
        task_id: str,
    ) -> tuple[
        EvaluationSessionRecord | None,
        ConversationRecord | None,
        TaskRecord | None,
        AlarmEventRecord | None,
    ]:
        with self._database.session_factory() as session:
            evaluation = session.get(EvaluationSessionRecord, evaluation_session_id)
            conversation = session.get(ConversationRecord, conversation_id)
            task = session.get(TaskRecord, task_id)
            alarm = session.scalar(
                select(AlarmEventRecord).where(AlarmEventRecord.task_id == task_id)
            )
            return evaluation, conversation, task, alarm

    def count_alarm_events(self, task_id: str) -> int:
        with self._database.session_factory() as session:
            return len(
                session.scalars(
                    select(AlarmEventRecord).where(AlarmEventRecord.task_id == task_id)
                ).all()
            )

    def get_task_snapshot(
        self, evaluation_session_id: str, task_id: str
    ) -> tuple[
        EvaluationSessionRecord | None,
        TaskRecord | None,
        AlarmEventRecord | None,
    ]:
        with self._database.session_factory() as session:
            evaluation = session.get(EvaluationSessionRecord, evaluation_session_id)
            task = session.get(TaskRecord, task_id)
            alarm = session.scalar(
                select(AlarmEventRecord).where(AlarmEventRecord.task_id == task_id)
            )
            return evaluation, task, alarm


def decode_idempotent_response(record: IdempotencyRecord) -> dict:
    return json.loads(record.response_json)
