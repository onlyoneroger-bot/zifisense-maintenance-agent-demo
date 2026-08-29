from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_mode: str = "competition"
    app_version: str = "0.1.0"
    api_version: str = "v1"
    database_url: str = "sqlite:///./data/agent.db"
    fixture_dir: Path = Field(default=Path("./fixtures"))

    # Public, development-only defaults. Deployment must override both hashes.
    evaluator_api_key_hash: str = "496e7a945ef82771e7d92976c76449daa5c6899ffd0c466632846a4e302b65ca"
    limited_api_key_hash: str = "e15d666e6ed2ac18a4af2bd61bebb3bb779d9c9ad1d369f0c0e18e569323adbe"
    rate_limit_total_per_minute: int = Field(default=60, ge=1)
    rate_limit_agent_per_minute: int = Field(default=20, ge=1)
