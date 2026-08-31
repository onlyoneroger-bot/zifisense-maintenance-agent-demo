from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from zifisense_agent_api.domain.llm_models import LLMTokenUsage

MICROS_PER_CNY = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class LLMBudgetPricing:
    usd_to_cny_rate: Decimal
    cache_hit_usd_per_million: Decimal
    cache_miss_usd_per_million: Decimal
    output_usd_per_million: Decimal

    @staticmethod
    def _to_micros(tokens: int, usd_per_million: Decimal, rate: Decimal) -> int:
        return int(
            (Decimal(tokens) * usd_per_million * rate).to_integral_value(rounding=ROUND_CEILING)
        )

    def reservation_micros(self, input_token_upper_bound: int, max_output_tokens: int) -> int:
        input_cost = self._to_micros(
            input_token_upper_bound,
            self.cache_miss_usd_per_million,
            self.usd_to_cny_rate,
        )
        output_cost = self._to_micros(
            max_output_tokens,
            self.output_usd_per_million,
            self.usd_to_cny_rate,
        )
        return input_cost + output_cost

    def actual_micros(self, usage: LLMTokenUsage) -> int:
        return sum(
            (
                self._to_micros(
                    usage.prompt_cache_hit_tokens,
                    self.cache_hit_usd_per_million,
                    self.usd_to_cny_rate,
                ),
                self._to_micros(
                    usage.prompt_cache_miss_tokens,
                    self.cache_miss_usd_per_million,
                    self.usd_to_cny_rate,
                ),
                self._to_micros(
                    usage.completion_tokens,
                    self.output_usd_per_million,
                    self.usd_to_cny_rate,
                ),
            )
        )


def cny_to_micros(amount: Decimal) -> int:
    return int((amount * MICROS_PER_CNY).to_integral_value(rounding=ROUND_CEILING))
