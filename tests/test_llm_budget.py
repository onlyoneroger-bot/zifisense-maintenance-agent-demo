from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from zifisense_agent_api.adapters.llm.base import (
    LLMBudgetExceededError,
    LLMProviderError,
)
from zifisense_agent_api.adapters.llm.budgeted import BudgetedLLMProvider
from zifisense_agent_api.domain.llm_budget import LLMBudgetPricing, cny_to_micros
from zifisense_agent_api.domain.llm_models import (
    LLMAnswerRequest,
    LLMEnhancement,
    LLMTokenUsage,
)
from zifisense_agent_api.infrastructure.database import Database
from zifisense_agent_api.infrastructure.llm_budget_repository import LLMBudgetRepository


def pricing() -> LLMBudgetPricing:
    return LLMBudgetPricing(
        usd_to_cny_rate=Decimal("7.00"),
        cache_hit_usd_per_million=Decimal("0.014"),
        cache_miss_usd_per_million=Decimal("0.44"),
        output_usd_per_million=Decimal("1.32"),
    )


def request(request_id: str = "req-budget") -> LLMAnswerRequest:
    return LLMAnswerRequest(
        request_id=request_id,
        user_message="查看当前设备状态",
        intent="OVERVIEW",
        task_state="CONTEXT_COLLECTING",
        deterministic_answer="确定性回答",
        diagnosis_text="候选诊断",
        diagnosis_confidence=0.8,
        evidence=[],
    )


class FakeUsageProvider:
    provider = "deepseek"
    model = "deepseek-v4-flash"
    max_output_tokens = 1200

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def estimate_input_token_upper_bound(self, _request: LLMAnswerRequest) -> int:
        return 1000

    def synthesize(self, _request: LLMAnswerRequest) -> LLMEnhancement:
        self.calls += 1
        if self.fail:
            raise LLMProviderError("provider unavailable")
        return LLMEnhancement(
            answer="增强回答",
            cited_evidence_ids=[],
            provider=self.provider,
            model=self.model,
            latency_ms=5,
            usage=LLMTokenUsage(
                prompt_cache_hit_tokens=100,
                prompt_cache_miss_tokens=900,
                completion_tokens=100,
            ),
        )


@pytest.fixture
def database(tmp_path: Path):
    db = Database(f"sqlite:///{(tmp_path / 'budget.db').as_posix()}")
    db.create_schema()
    yield db
    db.close()


def budgeted_provider(
    repository: LLMBudgetRepository,
    provider: FakeUsageProvider,
    *,
    limit_micros: int,
    clock,
) -> BudgetedLLMProvider:
    return BudgetedLLMProvider(
        provider=provider,
        repository=repository,
        pricing=pricing(),
        daily_limit_micros_cny=limit_micros,
        timezone="Asia/Shanghai",
        clock=clock,
    )


def test_pricing_uses_integer_micro_cny_and_peak_reservation():
    calculator = pricing()
    assert cny_to_micros(Decimal("10.00")) == 10_000_000
    assert calculator.reservation_micros(1000, 1200) == 14_168
    assert (
        calculator.actual_micros(
            LLMTokenUsage(
                prompt_cache_hit_tokens=100,
                prompt_cache_miss_tokens=900,
                completion_tokens=100,
            )
        )
        == 3_706
    )


def test_success_settles_actual_usage_and_persists_across_restart(tmp_path: Path):
    database_path = tmp_path / "persistent-budget.db"
    first_database = Database(f"sqlite:///{database_path.as_posix()}")
    first_database.create_schema()
    repository = LLMBudgetRepository(first_database)
    provider = FakeUsageProvider()
    wrapped = budgeted_provider(
        repository,
        provider,
        limit_micros=20_000,
        clock=lambda: datetime.fromisoformat("2026-08-30T12:00:00+08:00"),
    )
    result = wrapped.synthesize(request())

    assert result.answer == "增强回答"
    snapshot = repository.get_snapshot(
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
    )
    assert snapshot is not None
    assert snapshot.spent_micros_cny == 3_706
    assert snapshot.reserved_micros_cny == 0
    ledger = repository.list_ledger()
    assert len(ledger) == 1
    assert ledger[0].status == "SETTLED"
    assert ledger[0].prompt_cache_hit_tokens == 100

    first_database.close()
    reopened_database = Database(f"sqlite:///{database_path.as_posix()}")
    reopened_database.create_schema()
    reopened = LLMBudgetRepository(reopened_database)
    persisted = reopened.get_snapshot(
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
    )
    assert persisted == snapshot
    reopened_database.close()


def test_budget_rejection_does_not_call_provider(database: Database):
    repository = LLMBudgetRepository(database)
    provider = FakeUsageProvider()
    wrapped = budgeted_provider(
        repository,
        provider,
        limit_micros=10_000,
        clock=lambda: datetime.fromisoformat("2026-08-30T12:00:00+08:00"),
    )

    with pytest.raises(LLMBudgetExceededError):
        wrapped.synthesize(request())
    assert provider.calls == 0
    assert repository.list_ledger() == []


def test_provider_failure_forfeits_full_reservation(database: Database):
    repository = LLMBudgetRepository(database)
    provider = FakeUsageProvider(fail=True)
    wrapped = budgeted_provider(
        repository,
        provider,
        limit_micros=20_000,
        clock=lambda: datetime.fromisoformat("2026-08-30T12:00:00+08:00"),
    )

    with pytest.raises(LLMProviderError):
        wrapped.synthesize(request())
    snapshot = repository.get_snapshot(
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
    )
    assert snapshot is not None
    assert snapshot.spent_micros_cny == 14_168
    assert snapshot.reserved_micros_cny == 0
    assert repository.list_ledger()[0].status == "FORFEITED"


def test_budget_resets_on_beijing_calendar_day(database: Database):
    repository = LLMBudgetRepository(database)
    provider = FakeUsageProvider()
    current = [datetime.fromisoformat("2026-08-30T23:59:59+08:00")]
    wrapped = budgeted_provider(
        repository,
        provider,
        limit_micros=15_000,
        clock=lambda: current[0],
    )

    wrapped.synthesize(request("day-one"))
    with pytest.raises(LLMBudgetExceededError):
        wrapped.synthesize(request("day-one-rejected"))
    current[0] = datetime.fromisoformat("2026-08-31T00:00:01+08:00")
    wrapped.synthesize(request("day-two"))
    assert provider.calls == 2
    assert (
        repository.get_snapshot(
            budget_date="2026-08-31",
            timezone="Asia/Shanghai",
        )
        is not None
    )


def test_concurrent_reservations_never_exceed_limit(database: Database):
    repository = LLMBudgetRepository(database)
    limit = 10_000_000
    amount = 2_000_000

    def reserve(index: int):
        return repository.try_reserve(
            request_id=f"req-{index}",
            budget_date="2026-08-30",
            timezone="Asia/Shanghai",
            limit_micros_cny=limit,
            reservation_micros_cny=amount,
            provider="deepseek",
            model="deepseek-v4-flash",
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        reservations = list(executor.map(reserve, range(10)))

    accepted = [item for item in reservations if item is not None]
    snapshot = repository.get_snapshot(
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
    )
    assert len(accepted) == 5
    assert snapshot is not None
    assert snapshot.spent_micros_cny + snapshot.reserved_micros_cny == limit


def test_lowered_limit_is_visible_even_when_new_reservation_is_rejected(
    database: Database,
):
    repository = LLMBudgetRepository(database)
    first = repository.try_reserve(
        request_id="initial",
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
        limit_micros_cny=10_000_000,
        reservation_micros_cny=2_000_000,
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    rejected = repository.try_reserve(
        request_id="after-limit-change",
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
        limit_micros_cny=1_000_000,
        reservation_micros_cny=1,
        provider="deepseek",
        model="deepseek-v4-flash",
    )

    assert first is not None
    assert rejected is None
    snapshot = repository.get_snapshot(
        budget_date="2026-08-30",
        timezone="Asia/Shanghai",
    )
    assert snapshot is not None
    assert snapshot.limit_micros_cny == 1_000_000
