from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GuidanceProfile = Literal[
    "INTAKE",
    "NAVIGATION",
    "EVIDENCE",
    "FIELD_EVIDENCE",
    "DECISION_TRANSITION",
    "VALIDATION_ORCHESTRATION",
]
GuidanceUrgency = Literal["ROUTINE", "PRIORITY", "URGENT", "CRITICAL"]
GuidanceActionability = Literal[
    "INFORM",
    "INVESTIGATE",
    "DECISION_PENDING",
    "APPROVAL_REQUIRED",
    "COMPLETE",
]
GuidanceOwner = Literal[
    "USER",
    "SYSTEM",
    "DUTY_ENGINEER",
    "RELIABILITY_ENGINEER",
    "FIELD_TECHNICIAN",
    "MAINTENANCE_TEAM",
    "AUTHORIZED_APPROVER",
]


class GuidanceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str
    why: str
    owner: GuidanceOwner
    required_inputs: list[str] = Field(default_factory=list)
    requires_consent: bool = False
    requires_approval: bool = False
    blocking: bool = False
    next_tool: str | None = None


class GuidanceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: GuidanceProfile
    summary: str
    urgency: GuidanceUrgency
    current_stage: str
    actionability: GuidanceActionability
    next_steps: list[GuidanceStep]
    blocking_questions: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    recommended_next_tools: list[str] = Field(default_factory=list)
