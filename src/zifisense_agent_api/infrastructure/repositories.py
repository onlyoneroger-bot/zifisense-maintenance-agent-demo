from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from zifisense_agent_api.domain.entities import AlarmFixture, EvaluationBundle
from zifisense_agent_api.infrastructure.database import (
    AlarmEventRecord,
    ConversationRecord,
    ConversationTurnRecord,
    Database,
    EvaluationSessionRecord,
    FieldMeasurementEventRecord,
    FieldMeasurementRequestRecord,
    HumanClaimRecord,
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

    def update_task_state(self, task_id: str, state: str) -> None:
        with self._database.session_factory.begin() as session:
            task = session.get(TaskRecord, task_id)
            if task is not None:
                task.state = state

    def append_conversation_turn(
        self,
        *,
        evaluation_session_id: str,
        conversation_id: str,
        task_id: str,
        message: str,
        intent: str,
        answer: str,
        tool_names: list[str],
    ) -> None:
        with self._database.session_factory.begin() as session:
            session.add(
                ConversationTurnRecord(
                    evaluation_session_id=evaluation_session_id,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    message=message,
                    intent=intent,
                    answer=answer,
                    tool_names_json=json.dumps(tool_names, ensure_ascii=False),
                    created_at=iso_now(),
                )
            )

    def list_conversation_turns(self, task_id: str) -> list[ConversationTurnRecord]:
        with self._database.session_factory() as session:
            return list(
                session.scalars(
                    select(ConversationTurnRecord)
                    .where(ConversationTurnRecord.task_id == task_id)
                    .order_by(ConversationTurnRecord.id)
                ).all()
            )

    def add_human_claim(
        self,
        *,
        evaluation_session_id: str,
        task_id: str,
        claim_text: str,
        observed_at: str,
    ) -> tuple[HumanClaimRecord, bool]:
        with self._database.session_factory.begin() as session:
            existing = session.scalar(
                select(HumanClaimRecord).where(
                    HumanClaimRecord.task_id == task_id,
                    HumanClaimRecord.claim_text == claim_text,
                )
            )
            if existing is not None:
                return existing, False
            record = HumanClaimRecord(
                evidence_id=f"evd_human_{uuid.uuid4().hex}",
                evaluation_session_id=evaluation_session_id,
                task_id=task_id,
                claim_text=claim_text,
                source_role="EVALUATOR_USER",
                quality_status="UNVERIFIED",
                observed_at=observed_at,
                created_at=iso_now(),
            )
            session.add(record)
            session.flush()
            return record, True

    def list_human_claims(self, task_id: str) -> list[HumanClaimRecord]:
        with self._database.session_factory() as session:
            return list(
                session.scalars(
                    select(HumanClaimRecord)
                    .where(HumanClaimRecord.task_id == task_id)
                    .order_by(HumanClaimRecord.id)
                ).all()
            )

    def get_or_create_field_measurement_request(
        self,
        *,
        evaluation_session_id: str,
        task_id: str,
        asset_id: str,
        measurement_point_id: str,
    ) -> tuple[FieldMeasurementRequestRecord, bool]:
        with self._database.session_factory.begin() as session:
            existing = session.scalar(
                select(FieldMeasurementRequestRecord).where(
                    FieldMeasurementRequestRecord.task_id == task_id
                )
            )
            if existing is not None:
                return existing, False
            record = FieldMeasurementRequestRecord(
                id=f"fmr_{uuid.uuid4().hex}",
                evaluation_session_id=evaluation_session_id,
                task_id=task_id,
                asset_id=asset_id,
                measurement_point_id=measurement_point_id,
                status="REQUESTED",
                created_at=iso_now(),
            )
            session.add(record)
            task = session.get(TaskRecord, task_id)
            if task is not None:
                task.state = "FIELD_EVIDENCE_PENDING"
            session.flush()
            return record, True

    def get_field_measurement_request(
        self, task_id: str
    ) -> FieldMeasurementRequestRecord | None:
        with self._database.session_factory() as session:
            return session.scalar(
                select(FieldMeasurementRequestRecord).where(
                    FieldMeasurementRequestRecord.task_id == task_id
                )
            )

    def get_field_measurement_event(
        self, event_id: str
    ) -> FieldMeasurementEventRecord | None:
        with self._database.session_factory() as session:
            return session.get(FieldMeasurementEventRecord, event_id)

    def add_field_measurement_event(
        self,
        *,
        event_id: str,
        evaluation_session_id: str,
        task_id: str,
        source_system: str,
        occurred_at: str,
        asset_id: str,
        measurement_point_id: str,
        collection_quality: str,
        payload: dict,
    ) -> tuple[FieldMeasurementEventRecord, TaskRecord]:
        with self._database.session_factory.begin() as session:
            record = FieldMeasurementEventRecord(
                event_id=event_id,
                evaluation_session_id=evaluation_session_id,
                task_id=task_id,
                source_system=source_system,
                occurred_at=occurred_at,
                asset_id=asset_id,
                measurement_point_id=measurement_point_id,
                collection_quality=collection_quality,
                payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                evidence_id=f"evd_field_{uuid.uuid4().hex}",
                is_simulated=True,
                created_at=iso_now(),
            )
            task = session.get(TaskRecord, task_id)
            assert task is not None
            task.evidence_version += 1
            task.state = (
                "HUMAN_DECISION"
                if collection_quality == "PASS"
                else "FIELD_EVIDENCE_PENDING"
            )
            request_record = session.scalar(
                select(FieldMeasurementRequestRecord).where(
                    FieldMeasurementRequestRecord.task_id == task_id
                )
            )
            if request_record is not None:
                request_record.status = (
                    "COMPLETED" if collection_quality == "PASS" else "RETRY_REQUIRED"
                )
            session.add(record)
            session.flush()
            return record, task

    def list_field_measurement_events(
        self, task_id: str
    ) -> list[FieldMeasurementEventRecord]:
        with self._database.session_factory() as session:
            return list(
                session.scalars(
                    select(FieldMeasurementEventRecord)
                    .where(FieldMeasurementEventRecord.task_id == task_id)
                    .order_by(FieldMeasurementEventRecord.created_at)
                ).all()
            )


def decode_idempotent_response(record: IdempotencyRecord) -> dict:
    return json.loads(record.response_json)
