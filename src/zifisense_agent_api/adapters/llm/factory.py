from __future__ import annotations

from zifisense_agent_api.adapters.llm.base import LLMProvider
from zifisense_agent_api.adapters.llm.budgeted import BudgetedLLMProvider
from zifisense_agent_api.adapters.llm.deepseek import DeepSeekProvider
from zifisense_agent_api.config import Settings
from zifisense_agent_api.domain.llm_budget import LLMBudgetPricing, cny_to_micros
from zifisense_agent_api.infrastructure.llm_budget_repository import LLMBudgetRepository


def build_llm_provider(
    settings: Settings,
    budget_repository: LLMBudgetRepository | None = None,
) -> LLMProvider | None:
    if not settings.llm_enabled:
        return None
    assert settings.deepseek_api_key is not None
    provider = DeepSeekProvider(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_output_tokens=settings.llm_max_output_tokens,
        prompt_version=settings.llm_prompt_version,
    )
    if budget_repository is None:
        return provider
    return BudgetedLLMProvider(
        provider=provider,
        repository=budget_repository,
        pricing=LLMBudgetPricing(
            usd_to_cny_rate=settings.llm_usd_to_cny_rate,
            cache_hit_usd_per_million=(settings.deepseek_input_cache_hit_usd_per_million),
            cache_miss_usd_per_million=(settings.deepseek_input_cache_miss_usd_per_million),
            output_usd_per_million=settings.deepseek_output_usd_per_million,
        ),
        daily_limit_micros_cny=cny_to_micros(settings.llm_daily_budget_cny),
        timezone=settings.llm_budget_timezone,
    )
