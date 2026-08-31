from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from zifisense_agent_api.adapters.llm.base import LLMProviderError
from zifisense_agent_api.domain.llm_models import (
    LLMAnswerRequest,
    LLMAnswerResult,
    LLMEnhancement,
    LLMTokenUsage,
)

SYSTEM_PROMPT = """你是工业设备预测性维护助手，只负责润色系统已经形成的确定性分析。
必须遵守以下规则：
1. 仅使用输入 JSON 中的事实和证据，不得补充外部事实、数值、故障结论或控制指令。
2. 不得把推测写成已确认结论；证据不足时明确说明不确定性。
3. 不得提出停机、启停、PLC/DCS 写入或绕过人工审批的操作。
4. cited_evidence_ids 只能从输入 evidence 的 evidence_id 中选择。
5. 只返回一个 JSON 对象，不要 Markdown，不要解释。JSON 结构如下：
{"answer":"面向工程人员的中文答复","cited_evidence_ids":["输入中的证据ID"],"uncertainty_statement":"不确定性说明或null"}
"""


class DeepSeekProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        max_output_tokens: int,
        prompt_version: str,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._prompt_version = prompt_version
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def provider(self) -> str:
        return "deepseek"

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_output_tokens(self) -> int:
        return self._max_output_tokens

    def _messages(self, request: LLMAnswerRequest) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": f"{SYSTEM_PROMPT}\n提示词版本：{self._prompt_version}",
            },
            {
                "role": "user",
                "content": request.model_dump_json(exclude_none=True),
            },
        ]

    def estimate_input_token_upper_bound(self, request: LLMAnswerRequest) -> int:
        serialized = json.dumps(
            self._messages(request),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return len(serialized.encode("utf-8")) + 1024

    def synthesize(self, request: LLMAnswerRequest) -> LLMEnhancement:
        started = perf_counter()
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(request),
                response_format={"type": "json_object"},
                max_tokens=self._max_output_tokens,
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise LLMProviderError("LLM returned empty content.")
            result = LLMAnswerResult.model_validate(json.loads(content))
            allowed_ids = {item.evidence_id for item in request.evidence}
            if any(item not in allowed_ids for item in result.cited_evidence_ids):
                raise LLMProviderError("LLM cited evidence outside the supplied set.")
            answer = result.answer.strip()
            if not answer:
                raise LLMProviderError("LLM returned an empty answer.")
            if result.uncertainty_statement:
                uncertainty = result.uncertainty_statement.strip()
                if uncertainty and uncertainty not in answer:
                    answer = f"{answer}\n\n不确定性：{uncertainty}"
            normalized_answer = "".join(answer.casefold().split())
            prohibited_actions = (
                "立即停机",
                "启动设备",
                "写入plc",
                "写入dcs",
                "下发控制",
                "绕过审批",
            )
            if any(action in normalized_answer for action in prohibited_actions):
                raise LLMProviderError("LLM returned a prohibited control action.")
            raw_usage = completion.usage
            if raw_usage is None:
                raise LLMProviderError("LLM response did not include token usage.")
            prompt_tokens = int(raw_usage.prompt_tokens)
            raw_cache_hit_tokens = getattr(raw_usage, "prompt_cache_hit_tokens", None)
            cache_hit_tokens = int(raw_cache_hit_tokens or 0)
            raw_cache_miss_tokens = getattr(
                raw_usage,
                "prompt_cache_miss_tokens",
                None,
            )
            cache_miss_tokens = (
                max(0, prompt_tokens - cache_hit_tokens)
                if raw_cache_miss_tokens is None
                else int(raw_cache_miss_tokens)
            )
            return LLMEnhancement(
                answer=answer,
                cited_evidence_ids=result.cited_evidence_ids,
                provider=self.provider,
                model=self.model,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                usage=LLMTokenUsage(
                    prompt_cache_hit_tokens=cache_hit_tokens,
                    prompt_cache_miss_tokens=cache_miss_tokens,
                    completion_tokens=int(raw_usage.completion_tokens),
                ),
            )
        except LLMProviderError:
            raise
        except (json.JSONDecodeError, ValidationError, IndexError, AttributeError) as exc:
            raise LLMProviderError("LLM returned an invalid structured response.") from exc
        except Exception as exc:
            raise LLMProviderError("LLM provider request failed.") from exc
