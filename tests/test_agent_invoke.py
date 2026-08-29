from pathlib import Path

from conftest import AUTH_HEADERS, create_evaluation, make_settings
from fastapi.testclient import TestClient

from zifisense_agent_api.main import create_app


def invoke_payload(data: dict, **overrides) -> dict:
    payload = {
        "evaluation_session_id": data["evaluation_session_id"],
        "conversation_id": data["conversation_id"],
        "task_id": data["task_id"],
        "message": "当前设备发生了什么？",
        "locale": "zh-CN",
    }
    payload.update(overrides)
    return payload


def test_agent_returns_honest_fixture_based_degraded_response(client):
    data = create_evaluation(client)
    response = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["is_degraded"] is True
    assert body["data"]["task_state"] == "ALARM_RECEIVED"
    assert body["data"]["system_diagnosis"] == {
        "diagnosis_text": "齿轮故障/转子不平衡",
        "confidence": 0.82,
        "source_system": "PREDICTIVE_MAINTENANCE_SIMULATOR",
        "algorithm_version": "predictive-fixture-v1",
    }
    assert len(body["data"]["evidence"]) == 1
    assert body["data"]["evidence"][0]["evidence_type"] == "ALARM"
    assert body["data"]["evidence"][0]["is_simulated"] is True
    assert body["data"]["citations"] == []
    assert body["data"]["tool_executions"] == []
    assert body["data"]["agent_inferences"] == []
    assert body["data"]["pending_approval"] is None
    assert "模拟报警" in body["data"]["answer"]
    assert "尚未启用" in body["data"]["answer"]


def test_agent_rejects_cross_session_conversation_and_task(client):
    first = create_evaluation(client, "first-session-key")
    second = create_evaluation(client, "second-session-key")

    wrong_conversation = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(first, conversation_id=second["conversation_id"]),
    )
    wrong_task = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(first, task_id=second["task_id"]),
    )
    assert wrong_conversation.status_code == 403
    assert wrong_task.status_code == 403
    assert wrong_conversation.json()["error"]["code"] == "INSUFFICIENT_SCOPE"
    assert wrong_task.json()["error"]["code"] == "INSUFFICIENT_SCOPE"


def test_agent_returns_404_for_unknown_resources(client):
    data = create_evaluation(client)
    for field in ("evaluation_session_id", "conversation_id", "task_id"):
        response = client.post(
            "/api/v1/agent/invoke",
            headers=AUTH_HEADERS,
            json=invoke_payload(data, **{field: f"missing-{field}"}),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_agent_input_validation_is_400_not_422(client):
    data = create_evaluation(client)
    response = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data, message=""),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_agent_rate_limit_returns_contract_error(tmp_path: Path):
    app = create_app(
        make_settings(
            tmp_path,
            rate_limit_total_per_minute=100,
            rate_limit_agent_per_minute=1,
        )
    )
    with TestClient(app) as client:
        data = create_evaluation(client)
        first = client.post("/api/v1/agent/invoke", headers=AUTH_HEADERS, json=invoke_payload(data))
        limited = client.post(
            "/api/v1/agent/invoke", headers=AUTH_HEADERS, json=invoke_payload(data)
        )
    app.state.database.close()

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.json()["error"]["retryable"] is True
