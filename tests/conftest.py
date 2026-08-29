from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zifisense_agent_api.config import Settings
from zifisense_agent_api.main import create_app

EVALUATOR_KEY = "dev-evaluator-key"
LIMITED_KEY = "dev-limited-key"
AUTH_HEADERS = {"Authorization": f"Bearer {EVALUATOR_KEY}"}
LIMITED_HEADERS = {"Authorization": f"Bearer {LIMITED_KEY}"}


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'agent.db').as_posix()}",
        "rate_limit_total_per_minute": 1000,
        "rate_limit_agent_per_minute": 1000,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def app(tmp_path: Path):
    application = create_app(make_settings(tmp_path))
    yield application
    application.state.database.close()


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def create_evaluation(client: TestClient, key: str = "session-key-001") -> dict:
    response = client.post(
        "/api/v1/evaluation/sessions",
        headers={**AUTH_HEADERS, "Idempotency-Key": key},
        json={"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]
