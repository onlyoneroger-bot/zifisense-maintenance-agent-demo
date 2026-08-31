from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from zoneinfo import ZoneInfo

from zifisense_agent_api.adapters.llm.base import (
    LLMBudgetExceededError,
    LLMProvider,
    LLMProviderError,
)
from zifisense_agent_api.domain.llm_budget import LLMBudgetPricing
from zifisense_agent_api.domain.llm_models import LLMAnswerRequest, LLMEnhancement
from zifisense_agent_api.infrastructure.llm_budget_repository import LLMBudgetRepository


class BudgetedLLMProvider:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        repository: LLMBudgetRepository,
        pricing: LLMBudgetPricing,
        daily_limit_micros_cny: int,
        timezone: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._pricing = pricing
        self._daily_limit_micros_cny = daily_limit_micros_cny
        self._timezone = ZoneInfo(timezone)
        self._timezone_name = timezone
        self._clock = clock or (lambda: datetime.now(self._timezone))

    @property
    def provider(self) -> str:
        return self._provider.provider

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def max_output_tokens(self) -> int:
        return self._provider.max_output_tokens

    def estimate_input_token_upper_bound(self, request: LLMAnswerRequest) -> int:
        return self._provider.estimate_input_token_upper_bound(request)

    def _budget_date(self) -> str:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=self._timezone)
        else:
            now = now.astimezone(self._timezone)
        return now.date().isoformat()

    def synthesize(self, request: LLMAnswerRequest) -> LLMEnhancement:
        input_upper_bound = self.estimate_input_token_upper_bound(request)
        reservation_micros = self._pricing.reservation_micros(
            input_upper_bound,
            self.max_output_tokens,
        )
        try:
            reservation = self._repository.try_reserve(
                request_id=request.request_id,
                budget_date=self._budget_date(),
                timezone=self._timezone_name,
                limit_micros_cny=self._daily_limit_micros_cny,
                reservation_micros_cny=reservation_micros,
                provider=self.provider,
                model=self.model,
            )
        except Exception as exc:
            raise LLMProviderError("LLM budget reservation failed.") from exc
        if reservation is None:
            raise LLMBudgetExceededError("Daily LLM budget is exhausted.")

        try:
            result = self._provider.synthesize(request)
        except LLMProviderError:
            with suppress(Exception):
                self._repository.forfeit(reservation)
            raise
        except Exception as exc:
            with suppress(Exception):
                self._repository.forfeit(reservation)
            raise LLMProviderError("LLM provider request failed.") from exc

        actual_micros = self._pricing.actual_micros(result.usage)
        if actual_micros > reservation.reserved_micros_cny:
            with suppress(Exception):
                self._repository.forfeit(reservation)
            raise LLMProviderError("LLM usage exceeded the conservative reservation.")
        try:
            self._repository.settle(
                reservation,
                usage=result.usage,
                actual_micros_cny=actual_micros,
            )
        except Exception as exc:
            raise LLMProviderError("LLM budget settlement failed.") from exc
        return result
