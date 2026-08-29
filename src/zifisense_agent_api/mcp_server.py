from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from zifisense_agent_api.adapters.asset_fault_catalog import AssetFaultCatalog
from zifisense_agent_api.application.agent_facade import AgentFacade
from zifisense_agent_api.application.evaluation_service import EvaluationService
from zifisense_agent_api.application.event_service import EventService
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.mcp_models import (
    AssetListResult,
    DiagnosisStatus,
    FaultDetailResult,
    FaultHistoryResult,
    FaultListResult,
    FaultStatus,
    FieldMeasurementRequestResult,
    MaintenanceHistoryResult,
    MCPAgentInvokeResult,
    MonitoringStatus,
    MonitoringSummaryResult,
    OperatingContextResult,
    PeerComparisonResult,
    Severity,
    TaskResult,
)
from zifisense_agent_api.transport.schemas import (
    AgentInvokeRequest,
    CreateEvaluationSessionRequest,
    CreateEvaluationSessionResponse,
    FieldMeasurementCompletedEventRequest,
    FieldMeasurementCompletedPayload,
)

DetailModule = Literal[
    "asset",
    "diagnosis",
    "monitoring",
    "operating_context",
    "maintenance_history",
    "similar_faults",
    "peer_comparison",
    "evidence",
    "conflicts",
    "open_questions",
    "recommended_actions",
    "tool_executions",
    "timeline",
]


def _request_ids() -> tuple[str, str]:
    return f"mcp_req_{uuid.uuid4().hex}", f"trace_{uuid.uuid4().hex}"


def build_mcp_server(
    *,
    app_version: str,
    catalog: AssetFaultCatalog,
    evaluation_service: EvaluationService,
    agent_facade: AgentFacade,
    repository: EvaluationRepository,
    event_service: EventService,
) -> MCPServer:
    server = MCPServer(
        name="zifisense-intelligent-maintenance-agent",
        version=app_version,
        instructions=(
            "ZiFiSense competition maintenance Agent. All catalog data is simulated. "
            "Candidate diagnoses are not final engineering conclusions and no production-control "
            "tools are exposed."
        ),
    )

    @server.tool()
    def create_evaluation_session(
        scenario_id: Literal["reducer_gear_alarm_v1"],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        locale: str = "zh-CN",
    ) -> CreateEvaluationSessionResponse:
        """Create an isolated evaluation session and load its initial simulated alarm."""
        request_id, trace_id = _request_ids()
        try:
            result = evaluation_service.create(
                request=CreateEvaluationSessionRequest(scenario_id=scenario_id, locale=locale),
                client_id="evaluator",
                idempotency_key=idempotency_key,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return result

    @server.tool()
    def list_assets(
        site_id: str | None = None,
        line_id: str | None = None,
        asset_type: str | None = None,
        monitoring_status: MonitoringStatus | None = None,
        has_active_fault: bool | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> AssetListResult:
        """List simulated equipment with filters, stable sorting and cursor pagination."""
        try:
            return catalog.list_assets(
                site_id=site_id,
                line_id=line_id,
                asset_type=asset_type,
                monitoring_status=monitoring_status,
                has_active_fault=has_active_fault,
                keyword=keyword,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def list_current_faults(
        site_id: str | None = None,
        line_id: str | None = None,
        asset_id: str | None = None,
        severity: list[Severity] | None = None,
        fault_status: list[FaultStatus] | None = None,
        diagnosis_status: list[DiagnosisStatus] | None = None,
        detected_from: datetime | None = None,
        detected_to: datetime | None = None,
        requires_human: bool | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> FaultListResult:
        """List active simulated fault investigations; closed history is never mixed in."""
        try:
            return catalog.list_current_faults(
                site_id=site_id,
                line_id=line_id,
                asset_id=asset_id,
                severity=severity,
                fault_status=fault_status,
                diagnosis_status=diagnosis_status,
                detected_from=detected_from,
                detected_to=detected_to,
                requires_human=requires_human,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def get_fault_detail(
        fault_id: str,
        include: list[DetailModule] | None = None,
        history_limit: Annotated[int, Field(ge=0, le=20)] = 5,
    ) -> FaultDetailResult:
        """Get diagnosis, facts, inferences, limitations and evidence for one fault record."""
        try:
            return catalog.get_fault_detail(fault_id, include, history_limit)
        except KeyError as exc:
            raise ToolError(f"Fault record does not exist: {fault_id}") from exc

    @server.tool()
    def list_fault_history(
        asset_id: str | None = None,
        site_id: str | None = None,
        line_id: str | None = None,
        asset_type: str | None = None,
        fault_mode: str | None = None,
        diagnosis_status: list[DiagnosisStatus] | None = None,
        closed_from: datetime | None = None,
        closed_to: datetime | None = None,
        related_to_fault_id: str | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> FaultHistoryResult:
        """List closed history, preserving validated, rejected and inconclusive outcomes."""
        try:
            return catalog.list_fault_history(
                asset_id=asset_id,
                site_id=site_id,
                line_id=line_id,
                asset_type=asset_type,
                fault_mode=fault_mode,
                diagnosis_status=diagnosis_status,
                closed_from=closed_from,
                closed_to=closed_to,
                related_to_fault_id=related_to_fault_id,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def get_monitoring_summary(fault_id: str) -> MonitoringSummaryResult:
        """Get structured recent monitoring trends and data-quality status for a fault."""
        try:
            return catalog.get_monitoring_summary(fault_id)
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool()
    def get_operating_context(fault_id: str) -> OperatingContextResult:
        """Get load, speed, production and freshness context without inferring missing values."""
        try:
            return catalog.get_operating_context(fault_id)
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool()
    def get_maintenance_history(fault_id: str) -> MaintenanceHistoryResult:
        """Get structured maintenance records and their evidence quality for a current fault."""
        try:
            return catalog.get_maintenance_history(fault_id)
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool()
    def compare_peer_assets(fault_id: str) -> PeerComparisonResult:
        """Compare a faulted asset with selected peers and disclose comparability limits."""
        try:
            return catalog.compare_peer_assets(fault_id)
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool()
    def request_field_measurement(
        evaluation_session_id: str,
        task_id: str,
        consent: Literal[True],
    ) -> FieldMeasurementRequestResult:
        """Create one simulated field-measurement request after explicit user consent."""
        evaluation, task, alarm = repository.get_task_snapshot(evaluation_session_id, task_id)
        if evaluation is None or task is None or alarm is None:
            raise ToolError("Task or evaluation session does not exist.")
        if evaluation.client_id != "evaluator" or task.evaluation_session_id != evaluation.id:
            raise ToolError("Task access is forbidden.")
        record, created = repository.get_or_create_field_measurement_request(
            evaluation_session_id=evaluation.id,
            task_id=task.id,
            asset_id=task.asset_id,
            measurement_point_id=alarm.measurement_point_id,
        )
        return FieldMeasurementRequestResult(
            request_id=record.id,
            evaluation_session_id=evaluation.id,
            task_id=task.id,
            asset_id=record.asset_id,
            measurement_point_id=record.measurement_point_id,
            status=record.status,
            created=created,
            is_simulated=True,
        )

    @server.tool()
    def ingest_field_measurement_result(
        event_id: str,
        evaluation_session_id: str,
        task_id: str,
        asset_id: str,
        measurement_point_id: str,
        collection_quality: Literal["PASS", "FAIL", "PARTIAL"],
        sound_analysis: dict[str, Any],
        vibration_analysis: dict[str, Any],
        operating_condition: str | None = None,
        source_system: str = "PORTABLE_ANALYSIS_SIMULATOR",
    ) -> dict[str, Any]:
        """Ingest a simulated structured portable-analysis result; raw waveforms are excluded."""
        request_id, trace_id = _request_ids()
        try:
            result = event_service.ingest_field_measurement(
                request=FieldMeasurementCompletedEventRequest(
                    event_id=event_id,
                    event_type="FIELD_MEASUREMENT_COMPLETED",
                    source_system=source_system,
                    occurred_at=datetime.now().astimezone(),
                    evaluation_session_id=evaluation_session_id,
                    task_id=task_id,
                    payload=FieldMeasurementCompletedPayload(
                        asset_id=asset_id,
                        measurement_point_id=measurement_point_id,
                        collection_quality=collection_quality,
                        operating_condition=operating_condition,
                        sound_analysis=sound_analysis,
                        vibration_analysis=vibration_analysis,
                    ),
                ),
                client_id="evaluator",
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(mode="json")

    @server.tool()
    def agent_invoke(
        evaluation_session_id: str,
        conversation_id: str,
        task_id: str,
        message: Annotated[str, Field(min_length=1, max_length=8000)],
        locale: str = "zh-CN",
    ) -> MCPAgentInvokeResult:
        """Invoke the same Agent behavior exposed by the REST API."""
        request_id, trace_id = _request_ids()
        try:
            result = agent_facade.invoke(
                request=AgentInvokeRequest(
                    evaluation_session_id=evaluation_session_id,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    message=message,
                    locale=locale,
                ),
                client_id="evaluator",
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return MCPAgentInvokeResult(response=result.model_dump(mode="json"))

    @server.tool()
    def get_task(evaluation_session_id: str, task_id: str) -> TaskResult:
        """Read the persisted task and initial alarm for the current evaluation session."""
        evaluation, task, alarm = repository.get_task_snapshot(evaluation_session_id, task_id)
        if evaluation is None or task is None or alarm is None:
            raise ToolError("Task or evaluation session does not exist.")
        if evaluation.client_id != "evaluator" or task.evaluation_session_id != evaluation.id:
            raise ToolError("Task access is forbidden.")
        turns = repository.list_conversation_turns(task_id)
        claims = repository.list_human_claims(task_id)
        field_request = repository.get_field_measurement_request(task_id)
        field_measurements = repository.list_field_measurement_events(task_id)
        return TaskResult(
            task_id=task.id,
            evaluation_session_id=evaluation.id,
            task_state=task.state,
            asset_id=task.asset_id,
            alarm={
                "alarm_id": alarm.alarm_id,
                "severity": alarm.severity,
                "diagnosis_text": alarm.diagnosis_text,
                "confidence": alarm.confidence,
                "source_system": alarm.source_system,
                "observed_at": alarm.observed_at,
            },
            conversation_turns=[
                {
                    "turn_id": turn.id,
                    "message": turn.message,
                    "intent": turn.intent,
                    "answer": turn.answer,
                    "tool_names": json.loads(turn.tool_names_json),
                    "created_at": turn.created_at,
                }
                for turn in turns
            ],
            human_claims=[
                {
                    "evidence_id": claim.evidence_id,
                    "text": claim.claim_text,
                    "source_role": claim.source_role,
                    "quality_status": claim.quality_status,
                    "observed_at": claim.observed_at,
                }
                for claim in claims
            ],
            field_measurement_request=(
                {
                    "request_id": field_request.id,
                    "asset_id": field_request.asset_id,
                    "measurement_point_id": field_request.measurement_point_id,
                    "status": field_request.status,
                    "created_at": field_request.created_at,
                }
                if field_request is not None
                else None
            ),
            field_measurements=[
                {
                    "event_id": item.event_id,
                    "evidence_id": item.evidence_id,
                    "collection_quality": item.collection_quality,
                    "source_system": item.source_system,
                    "occurred_at": item.occurred_at,
                    "payload": json.loads(item.payload_json),
                }
                for item in field_measurements
            ],
            evidence_version=task.evidence_version,
            is_simulated=alarm.is_simulated,
        )

    return server
