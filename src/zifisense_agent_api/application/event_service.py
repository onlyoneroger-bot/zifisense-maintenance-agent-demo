from __future__ import annotations

import json
from datetime import datetime

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.domain.task_state import TaskState
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.schemas import (
    AlarmRaisedEventRequest,
    EventIngestData,
    EventIngestResponse,
    FieldMeasurementCompletedEventRequest,
    ResponseMeta,
    WorkOrderCompletedEventRequest,
)


class EventService:
    def __init__(self, repository: EvaluationRepository) -> None:
        self._repository = repository

    def ingest_field_measurement(
        self,
        *,
        request: FieldMeasurementCompletedEventRequest,
        client_id: str,
        request_id: str,
        trace_id: str,
    ) -> EventIngestResponse:
        evaluation, task, alarm = self._repository.get_task_snapshot(
            request.evaluation_session_id, request.task_id
        )

        if evaluation is None or task is None or alarm is None:
            raise ApplicationError(
                404, "RESOURCE_NOT_FOUND", "Task or evaluation session does not exist."
            )
        if evaluation.client_id != client_id or task.evaluation_session_id != evaluation.id:
            raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Task access is forbidden.")
        if request.payload.asset_id != task.asset_id:
            raise ApplicationError(
                400,
                "INVALID_REQUEST",
                "Measurement asset does not match the task asset.",
                details={"expected_asset_id": task.asset_id},
            )
        if request.payload.measurement_point_id != alarm.measurement_point_id:
            raise ApplicationError(
                400,
                "INVALID_REQUEST",
                "Measurement point does not match the requested point.",
                details={"expected_measurement_point_id": alarm.measurement_point_id},
            )
        field_request = self._repository.get_field_measurement_request(task.id)
        if field_request is None:
            raise ApplicationError(
                409,
                "INVALID_STATE_TRANSITION",
                "A field measurement result requires prior explicit consent and a request.",
            )

        duplicate = self._repository.get_field_measurement_event(request.event_id)
        if duplicate is not None:
            if (
                duplicate.evaluation_session_id != request.evaluation_session_id
                or duplicate.task_id != request.task_id
            ):
                raise ApplicationError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "The event_id was already used for another task.",
                )
            incoming_payload = json.dumps(
                request.payload.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            if duplicate.payload_json != incoming_payload:
                raise ApplicationError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "The event_id was replayed with a different payload.",
                )
            _, current_task, _ = self._repository.get_task_snapshot(
                request.evaluation_session_id, request.task_id
            )
            assert current_task is not None
            return self._response(
                request=request,
                task_state=current_task.state,
                duplicate=True,
                request_id=request_id,
                trace_id=trace_id,
            )

        _, updated_task = self._repository.add_field_measurement_event(
            event_id=request.event_id,
            evaluation_session_id=request.evaluation_session_id,
            task_id=request.task_id,
            source_system=request.source_system,
            occurred_at=request.occurred_at.isoformat(),
            asset_id=request.payload.asset_id,
            measurement_point_id=request.payload.measurement_point_id,
            collection_quality=request.payload.collection_quality,
            payload=request.payload.model_dump(mode="json"),
        )
        return self._response(
            request=request,
            task_state=updated_task.state,
            duplicate=False,
            request_id=request_id,
            trace_id=trace_id,
        )

    def ingest_alarm(
        self,
        *,
        request: AlarmRaisedEventRequest,
        client_id: str,
        request_id: str,
        trace_id: str,
    ) -> EventIngestResponse:
        evaluation = self._repository.get_evaluation_session(request.evaluation_session_id)
        if evaluation is None:
            raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Evaluation session does not exist.")
        if evaluation.client_id != client_id:
            raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Session access is forbidden.")
        duplicate = self._repository.get_alarm_by_external_event(request.event_id)
        if duplicate is not None:
            if (
                duplicate.alarm_id != request.payload.alarm_id
                or duplicate.asset_id != request.payload.asset_id
                or duplicate.diagnosis_text != request.payload.diagnosis_text
            ):
                raise ApplicationError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "The event_id was replayed with different data.",
                )
            _, task, _ = self._repository.get_task_owner_context(duplicate.task_id)
            assert task is not None
            return self._event_response(
                event_id=request.event_id,
                task_id=task.id,
                task_state=task.state,
                duplicate=True,
                request_id=request_id,
                trace_id=trace_id,
            )
        task = self._repository.add_alarm_event_task(
            evaluation_session_id=evaluation.id,
            event_id=request.event_id,
            alarm_id=request.payload.alarm_id,
            asset_id=request.payload.asset_id,
            measurement_point_id=request.payload.measurement_point_id,
            severity=request.payload.severity,
            diagnosis_text=request.payload.diagnosis_text,
            confidence=request.payload.confidence,
            algorithm_version=request.payload.algorithm_version,
            source_system=request.source_system,
            occurred_at=request.occurred_at.isoformat(),
            evidence_summary=(
                f"外部模拟报警：{request.payload.diagnosis_text}；"
                f"特征数 {len(request.payload.evidence_features)}。"
            ),
        )
        return self._event_response(
            event_id=request.event_id,
            task_id=task.id,
            task_state=task.state,
            duplicate=False,
            request_id=request_id,
            trace_id=trace_id,
        )

    def ingest_work_order_completion(
        self,
        *,
        request: WorkOrderCompletedEventRequest,
        client_id: str,
        request_id: str,
        trace_id: str,
    ) -> EventIngestResponse:
        evaluation, task, _ = self._repository.get_task_snapshot(
            request.evaluation_session_id, request.task_id
        )
        work_order = self._repository.get_work_order(request.task_id)
        if evaluation is None or task is None or work_order is None:
            raise ApplicationError(
                404, "RESOURCE_NOT_FOUND", "Task or submitted work order does not exist."
            )
        if evaluation.client_id != client_id or task.evaluation_session_id != evaluation.id:
            raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Task access is forbidden.")
        if work_order.id != request.payload.work_order_id:
            raise ApplicationError(400, "INVALID_REQUEST", "work_order_id does not match the task.")
        if work_order.status not in {"SUBMITTED", "IN_PROGRESS", "COMPLETED"}:
            raise ApplicationError(
                409,
                "INVALID_STATE_TRANSITION",
                "Work-order completion requires a previously approved submission.",
            )
        duplicate = self._repository.get_work_order_completion_event(request.event_id)
        if duplicate is not None:
            incoming_payload = json.dumps(
                request.payload.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            if duplicate.task_id != request.task_id or duplicate.payload_json != incoming_payload:
                raise ApplicationError(
                    409, "IDEMPOTENCY_CONFLICT", "The event_id was replayed with different data."
                )
            _, current_task, _ = self._repository.get_task_snapshot(
                request.evaluation_session_id, request.task_id
            )
            assert current_task is not None
            return self._event_response(
                event_id=request.event_id,
                task_id=request.task_id,
                task_state=current_task.state,
                duplicate=True,
                request_id=request_id,
                trace_id=trace_id,
            )

        diagnosis = request.payload.post_maintenance_diagnosis
        improved = diagnosis.get("improved")
        status = str(diagnosis.get("status", "")).upper()
        if improved is True or status in {"NORMAL", "IMPROVED", "RESOLVED"}:
            validation_status = "VERIFIED"
            summary = "维修后结构化诊断显示改善，当前模拟任务验证通过。"
        elif improved is False or status in {"ABNORMAL", "NOT_IMPROVED", "CONFLICTING"}:
            validation_status = "CONFLICTING"
            summary = "维修后结构化诊断未显示改善，需要继续复核，不能关闭调查。"
        else:
            validation_status = "PENDING"
            summary = "维修结果已记录，但缺少明确的维修后诊断结论，等待复核。"
        _, updated_task = self._repository.add_work_order_completion_event(
            event_id=request.event_id,
            evaluation_session_id=request.evaluation_session_id,
            task_id=request.task_id,
            work_order_id=request.payload.work_order_id,
            source_system=request.source_system,
            occurred_at=request.occurred_at.isoformat(),
            actual_fault=request.payload.actual_fault,
            payload=request.payload.model_dump(mode="json"),
            validation_status=validation_status,
            validation_summary=summary,
        )
        return self._event_response(
            event_id=request.event_id,
            task_id=request.task_id,
            task_state=updated_task.state,
            duplicate=False,
            request_id=request_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _response(
        *,
        request: FieldMeasurementCompletedEventRequest,
        task_state: str,
        duplicate: bool,
        request_id: str,
        trace_id: str,
    ) -> EventIngestResponse:
        return EventIngestResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=EventIngestData(
                event_id=request.event_id,
                accepted=True,
                task_id=request.task_id,
                task_state=TaskState(task_state),
                duplicate=duplicate,
            ),
            meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
        )

    @staticmethod
    def _event_response(
        *,
        event_id: str,
        task_id: str,
        task_state: str,
        duplicate: bool,
        request_id: str,
        trace_id: str,
    ) -> EventIngestResponse:
        return EventIngestResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=EventIngestData(
                event_id=event_id,
                accepted=True,
                task_id=task_id,
                task_state=TaskState(task_state),
                duplicate=duplicate,
            ),
            meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
        )
