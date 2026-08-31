from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from zifisense_agent_api.domain.llm_models import LLMTokenUsage
from zifisense_agent_api.infrastructure.database import (
    Database,
    LLMDailyBudgetRecord,
    LLMUsageLedgerRecord,
    iso_now,
)


@dataclass(frozen=True, slots=True)
class LLMBudgetReservation:
    ledger_id: str
    request_id: str
    budget_key: str
    reserved_micros_cny: int


@dataclass(frozen=True, slots=True)
class LLMBudgetSnapshot:
    budget_date: str
    timezone: str
    limit_micros_cny: int
    spent_micros_cny: int
    reserved_micros_cny: int


class LLMBudgetRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def try_reserve(
        self,
        *,
        request_id: str,
        budget_date: str,
        timezone: str,
        limit_micros_cny: int,
        reservation_micros_cny: int,
        provider: str,
        model: str,
    ) -> LLMBudgetReservation | None:
        budget_key = f"{budget_date}|{timezone}"
        ledger_id = f"llm_{uuid.uuid4().hex}"
        timestamp = iso_now()
        with self._database.session_factory.begin() as session:
            session.execute(
                sqlite_insert(LLMDailyBudgetRecord)
                .values(
                    budget_key=budget_key,
                    budget_date=budget_date,
                    timezone=timezone,
                    limit_micros_cny=limit_micros_cny,
                    spent_micros_cny=0,
                    reserved_micros_cny=0,
                    updated_at=timestamp,
                )
                .on_conflict_do_nothing(index_elements=["budget_key"])
            )
            session.execute(
                update(LLMDailyBudgetRecord)
                .where(LLMDailyBudgetRecord.budget_key == budget_key)
                .values(
                    limit_micros_cny=limit_micros_cny,
                    updated_at=timestamp,
                )
            )
            result = session.execute(
                update(LLMDailyBudgetRecord)
                .where(
                    LLMDailyBudgetRecord.budget_key == budget_key,
                    (
                        LLMDailyBudgetRecord.spent_micros_cny
                        + LLMDailyBudgetRecord.reserved_micros_cny
                        + reservation_micros_cny
                    )
                    <= limit_micros_cny,
                )
                .values(
                    reserved_micros_cny=(
                        LLMDailyBudgetRecord.reserved_micros_cny + reservation_micros_cny
                    ),
                    updated_at=timestamp,
                )
            )
            if result.rowcount != 1:
                return None
            session.add(
                LLMUsageLedgerRecord(
                    id=ledger_id,
                    request_id=request_id,
                    budget_key=budget_key,
                    provider=provider,
                    model=model,
                    reserved_micros_cny=reservation_micros_cny,
                    settled_micros_cny=0,
                    status="RESERVED",
                    created_at=timestamp,
                    settled_at=None,
                )
            )
        return LLMBudgetReservation(
            ledger_id=ledger_id,
            request_id=request_id,
            budget_key=budget_key,
            reserved_micros_cny=reservation_micros_cny,
        )

    def settle(
        self,
        reservation: LLMBudgetReservation,
        *,
        usage: LLMTokenUsage,
        actual_micros_cny: int,
    ) -> None:
        self._finalize(
            reservation,
            usage=usage,
            settled_micros_cny=actual_micros_cny,
            status="SETTLED",
        )

    def forfeit(self, reservation: LLMBudgetReservation) -> None:
        self._finalize(
            reservation,
            usage=LLMTokenUsage(),
            settled_micros_cny=reservation.reserved_micros_cny,
            status="FORFEITED",
        )

    def _finalize(
        self,
        reservation: LLMBudgetReservation,
        *,
        usage: LLMTokenUsage,
        settled_micros_cny: int,
        status: str,
    ) -> None:
        timestamp = iso_now()
        with self._database.session_factory.begin() as session:
            ledger = session.get(LLMUsageLedgerRecord, reservation.ledger_id)
            budget = session.get(LLMDailyBudgetRecord, reservation.budget_key)
            if ledger is None or budget is None or ledger.status != "RESERVED":
                return
            budget.reserved_micros_cny -= reservation.reserved_micros_cny
            budget.spent_micros_cny += settled_micros_cny
            budget.updated_at = timestamp
            ledger.prompt_cache_hit_tokens = usage.prompt_cache_hit_tokens
            ledger.prompt_cache_miss_tokens = usage.prompt_cache_miss_tokens
            ledger.completion_tokens = usage.completion_tokens
            ledger.settled_micros_cny = settled_micros_cny
            ledger.status = status
            ledger.settled_at = timestamp

    def get_snapshot(self, *, budget_date: str, timezone: str) -> LLMBudgetSnapshot | None:
        budget_key = f"{budget_date}|{timezone}"
        with self._database.session_factory() as session:
            record = session.get(LLMDailyBudgetRecord, budget_key)
            if record is None:
                return None
            return LLMBudgetSnapshot(
                budget_date=record.budget_date,
                timezone=record.timezone,
                limit_micros_cny=record.limit_micros_cny,
                spent_micros_cny=record.spent_micros_cny,
                reserved_micros_cny=record.reserved_micros_cny,
            )

    def list_ledger(self) -> list[LLMUsageLedgerRecord]:
        with self._database.session_factory() as session:
            return list(
                session.scalars(
                    select(LLMUsageLedgerRecord).order_by(LLMUsageLedgerRecord.created_at)
                ).all()
            )
