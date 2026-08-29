from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zifisense_agent_api.domain.task_state import TaskState


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"]
    version: str
    timestamp: datetime


class ResponseMeta(StrictModel):
    api_version: Literal["v1"] = "v1"
    timestamp: datetime
    is_degraded: bool


ErrorCode = Literal[
    "INVALID_REQUEST",
    "INVALID_ACCESS_TOKEN",
    "INSUFFICIENT_SCOPE",
    "RESOURCE_NOT_FOUND",
    "INVALID_STATE_TRANSITION",
    "EVIDENCE_VERSION_CONFLICT",
    "IDEMPOTENCY_CONFLICT",
    "APPROVAL_CHALLENGE_INVALID",
    "RATE_LIMITED",
    "MODEL_UNAVAILABLE",
    "SERVICE_UNAVAILABLE",
]


class ErrorBody(StrictModel):
    code: ErrorCode
    message: str
    retryable: bool
    details: dict[str, Any] | None = None


class ErrorResponse(StrictModel):
    request_id: str
    trace_id: str
    error: ErrorBody


class AgentSummary(StrictModel):
    name: str
    version: str
    locale: str


class ScenarioSummary(StrictModel):
    scenario_id: str
    name: str
    description: str
    suggested_questions: list[str]


CapabilityCode = Literal[
    "asset_catalog_query",
    "current_fault_query",
    "fault_detail_query",
    "fault_history_query",
    "monitoring_summary",
    "operating_context_query",
    "maintenance_history_query",
    "peer_comparison",
    "knowledge_retrieval",
    "context_orchestration",
    "evidence_conflict_detection",
    "human_input_gate",
    "portable_measurement_ingest",
    "work_order_draft",
    "approval_gated_write",
    "maintenance_result_validation",
    "audit_traceability",
]


class CapabilityItem(StrictModel):
    code: CapabilityCode
    name: str
    verification_hint: str


class CapabilitiesData(StrictModel):
    agent: AgentSummary
    scenarios: list[ScenarioSummary]
    capabilities: list[CapabilityItem]
    supported_event_types: list[
        Literal["ALARM_RAISED", "FIELD_MEASUREMENT_COMPLETED", "WORK_ORDER_COMPLETED"]
    ]
    safety_boundaries: list[str]


class CapabilitiesResponse(StrictModel):
    request_id: str
    trace_id: str
    data: CapabilitiesData
    meta: ResponseMeta


class CreateEvaluationSessionRequest(StrictModel):
    scenario_id: Literal["reducer_gear_alarm_v1"]
    locale: str = "zh-CN"


class CreateEvaluationSessionData(StrictModel):
    evaluation_session_id: str
    conversation_id: str
    task_id: str
    scenario_id: str
    task_state: TaskState
    scenario_summary: str
    suggested_questions: list[str]


class CreateEvaluationSessionResponse(StrictModel):
    request_id: str
    trace_id: str
    data: CreateEvaluationSessionData
    meta: ResponseMeta


class AgentInvokeRequest(StrictModel):
    evaluation_session_id: str
    conversation_id: str
    task_id: str
    message: str = Field(min_length=1, max_length=8000)
    locale: str = "zh-CN"


class Fact(StrictModel):
    text: str
    source_system: str
    observed_at: datetime
    evidence_id: str | None = None


class SystemDiagnosis(StrictModel):
    diagnosis_text: str
    confidence: float = Field(ge=0, le=1)
    source_system: str
    algorithm_version: str


class AgentInference(StrictModel):
    text: str
    supporting_evidence_ids: list[str]


class OpenQuestion(StrictModel):
    question: str
    reason: str
    blocking: bool


class EvidenceItem(StrictModel):
    evidence_id: str
    evidence_type: Literal[
        "ALARM",
        "KNOWLEDGE",
        "OPERATING_CONTEXT",
        "MAINTENANCE_HISTORY",
        "HUMAN_CLAIM",
        "PORTABLE_MEASUREMENT",
        "WORK_ORDER_RESULT",
    ]
    summary: str
    source_system: str
    observed_at: datetime
    quality_status: Literal["VALID", "INCOMPLETE", "STALE", "CONFLICTING", "UNVERIFIED", "REJECTED"]
    usage_level: Literal["RECORD_ONLY", "QUERY_GUIDANCE", "DECISION_REFERENCE", "VERIFIED_LABEL"]
    is_simulated: bool
    conflicts_with: list[str] | None = None


class Citation(StrictModel):
    document_id: str
    title: str
    locator: str
    excerpt: str | None = None


class ToolExecution(StrictModel):
    tool_name: str
    status: Literal["SUCCEEDED", "FAILED", "TIMED_OUT", "SKIPPED"]
    source_system: str
    elapsed_ms: int = Field(ge=0)
    is_simulated: bool | None = None


class RecommendedAction(StrictModel):
    code: str
    label: str
    requires_approval: bool


class PendingApproval(StrictModel):
    approval_id: str
    approval_challenge: str
    approval_type: Literal["SUBMIT_WORK_ORDER"]
    evidence_version: int = Field(ge=1)
    expires_at: datetime
    impact_preview: dict[str, Any] | None = None


class AgentResponseData(StrictModel):
    answer: str
    task_state: TaskState
    confirmed_facts: list[Fact]
    system_diagnosis: SystemDiagnosis
    agent_inferences: list[AgentInference]
    open_questions: list[OpenQuestion]
    evidence: list[EvidenceItem]
    citations: list[Citation]
    tool_executions: list[ToolExecution]
    recommended_actions: list[RecommendedAction]
    pending_approval: PendingApproval | None = None


class AgentInvokeResponse(StrictModel):
    request_id: str
    trace_id: str
    data: AgentResponseData
    meta: ResponseMeta


class FieldMeasurementCompletedPayload(StrictModel):
    asset_id: str
    measurement_point_id: str
    collection_quality: Literal["PASS", "FAIL", "PARTIAL"]
    operating_condition: str | None = None
    sound_analysis: dict[str, Any]
    vibration_analysis: dict[str, Any]


class FieldMeasurementCompletedEventRequest(StrictModel):
    event_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["FIELD_MEASUREMENT_COMPLETED"]
    source_system: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    evaluation_session_id: str
    task_id: str
    payload: FieldMeasurementCompletedPayload


class EventIngestData(StrictModel):
    event_id: str
    accepted: bool
    task_id: str
    task_state: TaskState
    duplicate: bool


class EventIngestResponse(StrictModel):
    request_id: str
    trace_id: str
    data: EventIngestData
    meta: ResponseMeta
