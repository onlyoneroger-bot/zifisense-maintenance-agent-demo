from __future__ import annotations

from typing import Protocol

from zifisense_agent_api.domain.llm_models import LLMAnswerRequest, LLMEnhancement


class LLMProviderError(RuntimeError):
    """Sanitized provider error safe for internal control flow."""


class LLMBudgetExceededError(LLMProviderError):
    """Raised before a provider call when the daily budget cannot be reserved."""


class LLMProvider(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def max_output_tokens(self) -> int: ...

    def estimate_input_token_upper_bound(self, request: LLMAnswerRequest) -> int: ...

    def synthesize(self, request: LLMAnswerRequest) -> LLMEnhancement: ...
