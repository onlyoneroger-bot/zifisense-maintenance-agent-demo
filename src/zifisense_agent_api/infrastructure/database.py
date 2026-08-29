from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, UniqueConstraint, create_engine
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
    created_at: Mapped[str] = mapped_column(String(64))


class AlarmEventRecord(Base):
    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alarm_id: Mapped[str] = mapped_column(String(128), index=True)
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

    def close(self) -> None:
        self.engine.dispose()


def iso_now() -> str:
    return datetime.now().astimezone().isoformat()
