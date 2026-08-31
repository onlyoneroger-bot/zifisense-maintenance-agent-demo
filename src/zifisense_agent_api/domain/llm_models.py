from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LLMEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: str
    summary: str
    quality_status: str
    usage_level: str


class LLMAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default="unknown", exclude=True)
    user_message: str
    intent: str
    task_state: str
    deterministic_answer: str
    diagnosis_text: str
    diagnosis_confidence: float = Field(ge=0, le=1)
    evidence: list[LLMEvidence]


class LLMAnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=8000)
    cited_evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    uncertainty_statement: str | None = Field(default=None, max_length=1000)


class LLMTokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_cache_hit_tokens: int = Field(default=0, ge=0)
    prompt_cache_miss_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class LLMEnhancement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    cited_evidence_ids: list[str]
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    usage: LLMTokenUsage = Field(default_factory=LLMTokenUsage)
