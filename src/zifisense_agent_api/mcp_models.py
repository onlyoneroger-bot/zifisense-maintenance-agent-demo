from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MCPModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


MonitoringStatus = Literal["ONLINE", "OFFLINE", "DEGRADED", "UNKNOWN"]
Severity = Literal["INFO", "WARNING", "MAJOR", "CRITICAL"]
FaultStatus = Literal[
    "OPEN",
    "INVESTIGATING",
    "WAITING_FIELD_EVIDENCE",
    "ACTION_PENDING",
    "MAINTENANCE_PROCESSING",
]
DiagnosisStatus = Literal[
    "CANDIDATE",
    "EVIDENCE_COLLECTING",
    "ENGINEER_CONFIRMED",
    "VALIDATED",
    "REJECTED",
    "INCONCLUSIVE",
]


class AssetSummary(MCPModel):
    asset_id: str
    asset_name: str
    site_id: str
    line_id: str
    asset_type: str
    model: str
    manufacturer: str
    criticality: str
    monitoring_status: MonitoringStatus
    latest_data_at: datetime
    measurement_point_ids: list[str]
    peer_group_id: str
    active_fault_count: int = Field(ge=0)
    highest_active_severity: Severity | None
    is_simulated: Literal[True]


class AssetListResult(MCPModel):
    items: list[AssetSummary]
    total: int = Field(ge=0)
    next_cursor: str | None
    notice: str
    is_simulated: Literal[True]


class FaultSummary(MCPModel):
    fault_id: str
    alarm_ids: list[str]
    asset_id: str
    asset_name: str
    title: str
    severity: Severity
    fault_status: FaultStatus
    diagnosis_status: DiagnosisStatus
    primary_diagnosis: str
    diagnosis_confidence: float = Field(ge=0, le=1)
    diagnosis_source: str
    algorithm_version: str
    detected_at: datetime
    latest_update_at: datetime
    task_id: str
    requires_human: bool
    evidence_version: int = Field(ge=1)
    next_action_summary: str
    is_simulated: Literal[True]


class FaultListResult(MCPModel):
    items: list[FaultSummary]
    total: int = Field(ge=0)
    next_cursor: str | None
    is_simulated: Literal[True]


class Similarity(MCPModel):
    score: float = Field(ge=0, le=1)
    matched_dimensions: list[str]
    differences: list[str]


class FaultHistoryItem(MCPModel):
    fault_id: str
    asset_id: str
    site_id: str
    line_id: str
    asset_type: str
    fault_mode: str
    title: str
    detected_at: datetime
    closed_at: datetime
    diagnosis_status: DiagnosisStatus
    validated_fault: str | None
    maintenance_action: str
    parts_replaced: list[str]
    effect_validation: str
    related_fault_ids: list[str]
    similarity: Similarity
    is_simulated: Literal[True]


class FaultHistoryResult(MCPModel):
    items: list[FaultHistoryItem]
    total: int = Field(ge=0)
    next_cursor: str | None
    is_simulated: Literal[True]


class FaultDetailResult(MCPModel):
    fault: dict[str, Any]
    asset: dict[str, Any] | None
    diagnosis: dict[str, Any] | None
    monitoring: dict[str, Any] | None
    operating_context: dict[str, Any] | None
    related_history: list[FaultHistoryItem]
    evidence: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    open_questions: list[str]
    recommended_actions: list[dict[str, Any]]
    task_id: str
    is_degraded: bool
    is_simulated: Literal[True]


class TaskResult(MCPModel):
    task_id: str
    evaluation_session_id: str
    task_state: str
    asset_id: str
    alarm: dict[str, Any]
    conversation_turns: list[dict[str, Any]]
    human_claims: list[dict[str, Any]]
    field_measurement_request: dict[str, Any] | None
    field_measurements: list[dict[str, Any]]
    evidence_version: int
    is_simulated: bool


class MCPAgentInvokeResult(MCPModel):
    response: dict[str, Any]


class MonitoringSummaryResult(MCPModel):
    fault_id: str
    asset_id: str
    window: str
    measurement_point_id: str
    overall_status: str
    trend: str
    features: list[dict[str, Any]]
    data_quality: str
    observed_at: datetime
    source_system: str
    evidence_id: str
    is_simulated: Literal[True]


class OperatingContextResult(MCPModel):
    fault_id: str
    asset_id: str
    status: str
    load_percent: float | None = None
    speed_rpm: float | None = None
    production_rate: float | None = None
    recipe: str | None = None
    starts_last_24h: int | None = None
    observed_at: datetime
    freshness: str
    missing_fields: list[str]
    source_system: str
    evidence_id: str
    is_simulated: Literal[True]


class MaintenanceHistoryResult(MCPModel):
    fault_id: str
    asset_id: str
    records: list[dict[str, Any]]
    source_system: str
    evidence_id: str
    is_simulated: Literal[True]


class PeerComparisonResult(MCPModel):
    fault_id: str
    subject_asset_id: str
    peer_group_id: str
    comparability: str
    subject_status: str
    peers: list[dict[str, Any]]
    analysis: str
    limitations: list[str]
    observed_at: datetime
    source_system: str
    evidence_id: str
    is_simulated: Literal[True]


class FieldMeasurementRequestResult(MCPModel):
    request_id: str
    evaluation_session_id: str
    task_id: str
    asset_id: str
    measurement_point_id: str
    status: str
    created: bool
    is_simulated: Literal[True]
