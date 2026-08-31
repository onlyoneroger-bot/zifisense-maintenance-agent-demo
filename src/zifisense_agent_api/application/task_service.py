from __future__ import annotations

import json
from datetime import datetime

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.domain.task_state import TaskState
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.schemas import (
    EvidenceConflict,
    EvidenceItem,
    MaintenanceValidation,
    PendingApproval,
    ResponseMeta,
    TaskSnapshot,
    TaskSnapshotResponse,
    TimelineEvent,
    ToolExecution,
    WorkOrderSummary,
)


class TaskService:
    def __init__(self, repository: EvaluationRepository) -> None:
        self._repository = repository

    def get_snapshot(
        self, *, task_id: str, client_id: str, request_id: str, trace_id: str
    ) -> TaskSnapshotResponse:
        evaluation, task, alarm = self._repository.get_task_owner_context(task_id)
        if evaluation is None or task is None or alarm is None:
            raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Task does not exist.")
        if evaluation.client_id != client_id:
            raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Task access is forbidden.")

        evidence = [
            EvidenceItem(
                evidence_id=alarm.evidence_id,
                evidence_type="ALARM",
                summary=alarm.evidence_summary,
                source_system=alarm.source_system,
                observed_at=datetime.fromisoformat(alarm.observed_at),
                quality_status="VALID",
                usage_level="DECISION_REFERENCE",
                is_simulated=alarm.is_simulated,
                conflicts_with=[],
            )
        ]
        timeline = [
            TimelineEvent(
                event_id=alarm.alarm_id,
                event_type="ALARM_RAISED",
                occurred_at=datetime.fromisoformat(alarm.observed_at),
                summary=alarm.evidence_summary,
            )
        ]
        for claim in self._repository.list_human_claims(task_id):
            evidence.append(
                EvidenceItem(
                    evidence_id=claim.evidence_id,
                    evidence_type="HUMAN_CLAIM",
                    summary=claim.claim_text,
                    source_system=claim.source_role,
                    observed_at=datetime.fromisoformat(claim.observed_at),
                    quality_status="UNVERIFIED",
                    usage_level="RECORD_ONLY",
                    is_simulated=True,
                    conflicts_with=[],
                )
            )
        for item in self._repository.list_field_measurement_events(task_id):
            payload = json.loads(item.payload_json)
            quality_map = {"PASS": "VALID", "PARTIAL": "INCOMPLETE", "FAIL": "REJECTED"}
            evidence.append(
                EvidenceItem(
                    evidence_id=item.evidence_id,
                    evidence_type="PORTABLE_MEASUREMENT",
                    summary=(
                        f"补测质量 {item.collection_quality}；"
                        f"振动：{payload['vibration_analysis'].get('summary', '无摘要')}。"
                    ),
                    source_system=item.source_system,
                    observed_at=datetime.fromisoformat(item.occurred_at),
                    quality_status=quality_map[item.collection_quality],
                    usage_level=(
                        "DECISION_REFERENCE" if item.collection_quality == "PASS" else "RECORD_ONLY"
                    ),
                    is_simulated=True,
                    conflicts_with=[],
                )
            )
            timeline.append(
                TimelineEvent(
                    event_id=item.event_id,
                    event_type="FIELD_MEASUREMENT_COMPLETED",
                    occurred_at=datetime.fromisoformat(item.occurred_at),
                    summary=f"现场补测质量 {item.collection_quality}",
                )
            )

        completions = self._repository.list_work_order_completion_events(task_id)
        conflicts: list[EvidenceConflict] = []
        maintenance_validation = None
        for item in completions:
            evidence_id = f"evd_work_{item.event_id}"
            evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    evidence_type="WORK_ORDER_RESULT",
                    summary=item.validation_summary,
                    source_system=item.source_system,
                    observed_at=datetime.fromisoformat(item.occurred_at),
                    quality_status=(
                        "CONFLICTING" if item.validation_status == "CONFLICTING" else "VALID"
                    ),
                    usage_level=(
                        "VERIFIED_LABEL"
                        if item.validation_status == "VERIFIED"
                        else "DECISION_REFERENCE"
                    ),
                    is_simulated=True,
                    conflicts_with=[],
                )
            )
            if item.validation_status == "CONFLICTING":
                conflicts.append(
                    EvidenceConflict(
                        conflict_id=f"conflict_{item.event_id}",
                        summary="维修后结构化诊断未显示改善，需要继续复核。",
                        evidence_ids=[alarm.evidence_id, evidence_id],
                        status="OPEN",
                    )
                )
            maintenance_validation = MaintenanceValidation(
                status=item.validation_status,
                actual_fault=item.actual_fault,
                sample_status=(
                    "PENDING_REVIEW" if item.validation_status != "VERIFIED" else "APPROVED"
                ),
                summary=item.validation_summary,
            )
            timeline.append(
                TimelineEvent(
                    event_id=item.event_id,
                    event_type="WORK_ORDER_COMPLETED",
                    occurred_at=datetime.fromisoformat(item.occurred_at),
                    summary=item.validation_summary,
                )
            )

        turns = self._repository.list_conversation_turns(task_id)
        tool_executions = [
            ToolExecution(
                tool_name=tool_name,
                status="SUCCEEDED",
                source_system="AUDIT_REPLAY",
                elapsed_ms=0,
                is_simulated=True,
            )
            for turn in turns
            for tool_name in json.loads(turn.tool_names_json)
        ]
        approval = self._repository.get_approval(task_id)
        pending_approval = (
            PendingApproval(
                approval_id=approval.id,
                approval_challenge=approval.approval_challenge,
                approval_type="SUBMIT_WORK_ORDER",
                evidence_version=approval.evidence_version,
                expires_at=datetime.fromisoformat(approval.expires_at),
                impact_preview={"target": "SIMULATED_EAM", "production_write": False},
            )
            if approval is not None and approval.status == "PENDING"
            else None
        )
        work_order = self._repository.get_work_order(task_id)
        work_order_summary = (
            WorkOrderSummary(
                work_order_id=work_order.id,
                status=work_order.status,
                title=work_order.title,
                recommended_window=work_order.recommended_window,
            )
            if work_order is not None
            else None
        )
        return TaskSnapshotResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=TaskSnapshot(
                task_id=task.id,
                evaluation_session_id=evaluation.id,
                task_state=TaskState(task.state),
                evidence_version=task.evidence_version,
                alarm={
                    "alarm_id": alarm.alarm_id,
                    "asset_id": alarm.asset_id,
                    "measurement_point_id": alarm.measurement_point_id,
                    "severity": alarm.severity,
                    "diagnosis_text": alarm.diagnosis_text,
                    "confidence": alarm.confidence,
                    "algorithm_version": alarm.algorithm_version,
                },
                evidence=evidence,
                conflicts=conflicts,
                tool_executions=tool_executions,
                pending_approval=pending_approval,
                work_order=work_order_summary,
                maintenance_validation=maintenance_validation,
                timeline=timeline,
            ),
            meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
        )
