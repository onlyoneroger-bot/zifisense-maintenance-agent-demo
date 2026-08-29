from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from zifisense_agent_api.domain.task_state import TaskState


@dataclass(frozen=True, slots=True)
class AlarmFixture:
    scenario_id: str
    scenario_name: str
    scenario_description: str
    suggested_questions: tuple[str, ...]
    asset_id: str
    asset_name: str
    measurement_point_id: str
    alarm_id: str
    alarm_time: datetime
    severity: str
    diagnosis_text: str
    confidence: float
    algorithm_version: str
    source_system: str
    evidence_summary: str
    is_simulated: bool


@dataclass(frozen=True, slots=True)
class EvaluationBundle:
    evaluation_session_id: str
    conversation_id: str
    task_id: str
    scenario_id: str
    task_state: TaskState
