from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class EvaluationSessionRecord(Base):
    __tablename__ = "evaluation_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str] = mapped_column(String(128))
    locale: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(64))


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    created_at: Mapped[str] = mapped_column(String(64))


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    state: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[str] = mapped_column(String(128))
    evidence_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[str] = mapped_column(String(64))


class AlarmEventRecord(Base):
    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alarm_id: Mapped[str] = mapped_column(String(128), index=True)
    external_event_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    asset_id: Mapped[str] = mapped_column(String(128))
    measurement_point_id: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32))
    diagnosis_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    algorithm_version: Mapped[str] = mapped_column(String(128))
    source_system: Mapped[str] = mapped_column(String(128))
    observed_at: Mapped[str] = mapped_column(String(64))
    evidence_id: Mapped[str] = mapped_column(String(64), unique=True)
    evidence_summary: Mapped[str] = mapped_column(Text)
    is_simulated: Mapped[bool] = mapped_column(Boolean)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("client_id", "operation", "idempotency_key", name="uq_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int]
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(64))


class ConversationTurnRecord(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(64))
    answer: Mapped[str] = mapped_column(Text)
    tool_names_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(64))


class LLMDailyBudgetRecord(Base):
    __tablename__ = "llm_daily_budgets"

    budget_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    budget_date: Mapped[str] = mapped_column(String(10), index=True)
    timezone: Mapped[str] = mapped_column(String(64))
    limit_micros_cny: Mapped[int] = mapped_column(BigInteger)
    spent_micros_cny: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_micros_cny: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[str] = mapped_column(String(64))


class LLMUsageLedgerRecord(Base):
    __tablename__ = "llm_usage_ledger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    budget_key: Mapped[str] = mapped_column(ForeignKey("llm_daily_budgets.budget_key"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_cache_hit_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    prompt_cache_miss_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_micros_cny: Mapped[int] = mapped_column(BigInteger)
    settled_micros_cny: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(64))
    settled_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class HumanClaimRecord(Base):
    __tablename__ = "human_claims"
    __table_args__ = (UniqueConstraint("task_id", "claim_text", name="uq_task_claim"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = mapped_column(String(64), unique=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    claim_text: Mapped[str] = mapped_column(Text)
    source_role: Mapped[str] = mapped_column(String(64))
    quality_status: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64))


class FieldMeasurementRequestRecord(Base):
    __tablename__ = "field_measurement_requests"
    __table_args__ = (UniqueConstraint("task_id", name="uq_field_request_task"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    asset_id: Mapped[str] = mapped_column(String(128))
    measurement_point_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(64))


class FieldMeasurementEventRecord(Base):
    __tablename__ = "field_measurement_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    source_system: Mapped[str] = mapped_column(String(128))
    occurred_at: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[str] = mapped_column(String(128))
    measurement_point_id: Mapped[str] = mapped_column(String(128))
    collection_quality: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[str] = mapped_column(String(64), unique=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(64))


class WorkOrderRecord(Base):
    __tablename__ = "work_orders"
    __table_args__ = (UniqueConstraint("task_id", name="uq_work_order_task"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    recommended_window: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(64))


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("task_id", name="uq_approval_task"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    approval_challenge: Mapped[str] = mapped_column(String(256))
    approval_type: Mapped[str] = mapped_column(String(64))
    evidence_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkOrderCompletionEventRecord(Base):
    __tablename__ = "work_order_completion_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evaluation_session_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_sessions.id"), index=True
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id"), index=True)
    source_system: Mapped[str] = mapped_column(String(128))
    occurred_at: Mapped[str] = mapped_column(String(64))
    actual_fault: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(32))
    validation_summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(64))


class Database:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///") and not url.endswith(":memory:"):
            raw_path = url.removeprefix("sqlite:///")
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name != "sqlite":
            return
        schema = inspect(self.engine)
        task_columns = {item["name"] for item in schema.get_columns("tasks")}
        alarm_columns = {item["name"] for item in schema.get_columns("alarm_events")}
        with self.engine.begin() as connection:
            if "evidence_version" not in task_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN evidence_version INTEGER NOT NULL DEFAULT 1")
                )
            if "external_event_id" not in alarm_columns:
                connection.execute(
                    text("ALTER TABLE alarm_events ADD COLUMN external_event_id VARCHAR(128)")
                )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_alarm_external_event_id "
                    "ON alarm_events(external_event_id)"
                )
            )

    def close(self) -> None:
        self.engine.dispose()


def iso_now() -> str:
    return datetime.now().astimezone().isoformat()
