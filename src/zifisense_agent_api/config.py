from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ApiScope = Literal[
    "capability:read",
    "evaluation:create",
    "agent:invoke",
    "event:write",
    "task:read",
    "approval:write",
    "admin:write",
    "mcp:use",
]


class ApiClientConfig(BaseModel):
    """One deployment-managed API client; only the key hash is persisted."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    api_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scopes: frozenset[ApiScope] = Field(min_length=1)
    enabled: bool = True


_API_CLIENT_LIST = TypeAdapter(list[ApiClientConfig])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_mode: str = "competition"
    app_version: str = "1.0.0"
    api_version: str = "v1"
    database_url: str = "sqlite:///./data/agent.db"
    fixture_dir: Path = Field(default=Path("./fixtures"))

    # Public, development-only defaults. Deployment must override both hashes.
    evaluator_api_key_hash: str = "496e7a945ef82771e7d92976c76449daa5c6899ffd0c466632846a4e302b65ca"
    limited_api_key_hash: str = "e15d666e6ed2ac18a4af2bd61bebb3bb779d9c9ad1d369f0c0e18e569323adbe"
    api_clients_json: SecretStr | None = None
    rate_limit_total_per_minute: int = Field(default=60, ge=1)
    rate_limit_agent_per_minute: int = Field(default=20, ge=1)
    rate_limit_mcp_per_minute: int = Field(default=100, ge=1)
    mcp_allowed_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1:*", "localhost:*", "testserver"]
    )
    mcp_allowed_origins: list[str] = Field(default_factory=list)
    mcp_sync_deadline_seconds: float = Field(default=25, ge=10, lt=30)

    llm_enabled: bool = False
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    llm_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=12, gt=0, le=120)
    llm_max_retries: int = Field(default=0, ge=0, le=5)
    llm_max_output_tokens: int = Field(default=1200, ge=256, le=8192)
    llm_prompt_version: str = "maintenance-agent-v1"
    llm_daily_budget_cny: Decimal = Field(default=Decimal("10.00"), gt=0)
    llm_budget_timezone: str = "Asia/Shanghai"
    llm_usd_to_cny_rate: Decimal = Field(default=Decimal("7.00"), gt=0)
    deepseek_input_cache_hit_usd_per_million: Decimal = Field(
        default=Decimal("0.014"),
        ge=0,
    )
    deepseek_input_cache_miss_usd_per_million: Decimal = Field(
        default=Decimal("0.44"),
        ge=0,
    )
    deepseek_output_usd_per_million: Decimal = Field(
        default=Decimal("1.32"),
        ge=0,
    )

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> Settings:
        configured_clients = self.configured_api_clients()
        if not configured_clients:
            legacy_hashes = (
                self.evaluator_api_key_hash,
                self.limited_api_key_hash,
            )
            if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in legacy_hashes):
                raise ValueError(
                    "Configure API_CLIENTS_JSON or provide both legacy API key hashes."
                )
        if not self.llm_enabled:
            return self
        if self.llm_provider.casefold() != "deepseek":
            raise ValueError("LLM_PROVIDER currently supports only 'deepseek'.")
        if self.deepseek_api_key is None or not self.deepseek_api_key.get_secret_value().strip():
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_ENABLED=true.")
        key_value = self.deepseek_api_key.get_secret_value().strip()
        if key_value.startswith("<") and key_value.endswith(">"):
            raise ValueError("DEEPSEEK_API_KEY must not include angle brackets.")
        if self.llm_max_retries != 0:
            raise ValueError(
                "LLM_MAX_RETRIES must be 0 while the MCP synchronous 30-second SLA is enabled."
            )
        provider_budget = self.mcp_sync_deadline_seconds - 5
        if self.llm_timeout_seconds > provider_budget:
            raise ValueError(
                "LLM_TIMEOUT_SECONDS must leave at least 5 seconds inside "
                "MCP_SYNC_DEADLINE_SECONDS for deterministic fallback."
            )
        try:
            ZoneInfo(self.llm_budget_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("LLM_BUDGET_TIMEZONE must be a valid IANA timezone.") from exc
        return self

    def configured_api_clients(self) -> tuple[ApiClientConfig, ...]:
        """Parse deployment clients without exposing the source JSON in errors."""

        if self.api_clients_json is None:
            return ()
        raw = self.api_clients_json.get_secret_value().strip()
        if not raw:
            return ()
        try:
            payload = json.loads(raw)
            clients = _API_CLIENT_LIST.validate_python(payload)
        except Exception as exc:
            raise ValueError(
                "API_CLIENTS_JSON must be a JSON array of valid client records."
            ) from exc
        if not clients:
            raise ValueError("API_CLIENTS_JSON must contain at least one client record.")

        client_ids = [client.client_id.casefold() for client in clients]
        key_hashes = [client.api_key_hash for client in clients]
        if len(client_ids) != len(set(client_ids)):
            raise ValueError("API_CLIENTS_JSON contains duplicate client_id values.")
        if len(key_hashes) != len(set(key_hashes)):
            raise ValueError("API_CLIENTS_JSON contains duplicate API key hashes.")
        if not any(client.enabled for client in clients):
            raise ValueError("API_CLIENTS_JSON must contain at least one enabled client.")
        return tuple(clients)
