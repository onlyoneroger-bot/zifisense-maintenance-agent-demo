from concurrent.futures import ThreadPoolExecutor

from conftest import AUTH_HEADERS, create_evaluation
from fastapi.testclient import TestClient


def test_create_session_persists_fixture_and_isolates_ids(client, app):
    data = create_evaluation(client)
    evaluation, conversation, task, alarm = app.state.repository.get_task_context(
        data["evaluation_session_id"], data["conversation_id"], data["task_id"]
    )

    assert evaluation is not None
    assert conversation is not None
    assert task is not None
    assert alarm is not None
    assert data["task_state"] == "ALARM_RECEIVED"
    assert alarm.asset_id == "ASSET-REDUCER-001"
    assert alarm.measurement_point_id == "MP-4F040B86-X"
    assert alarm.severity == "WARNING"
    assert alarm.diagnosis_text == "齿轮故障/转子不平衡"
    assert alarm.confidence == 0.82
    assert alarm.algorithm_version == "predictive-fixture-v1"
    assert alarm.observed_at == "2026-08-20T15:44:29+08:00"
    assert alarm.is_simulated is True
    assert app.state.repository.count_alarm_events(data["task_id"]) == 1


def test_idempotent_replay_returns_first_response(client):
    headers = {
        **AUTH_HEADERS,
        "Idempotency-Key": "same-session-key",
        "X-Request-ID": "same-request-id",
    }
    payload = {"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"}
    first = client.post("/api/v1/evaluation/sessions", headers=headers, json=payload)
    second = client.post("/api/v1/evaluation/sessions", headers=headers, json=payload)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


def test_idempotency_key_reuse_with_different_body_returns_409(client):
    headers = {**AUTH_HEADERS, "Idempotency-Key": "conflict-key-001"}
    first = client.post(
        "/api/v1/evaluation/sessions",
        headers=headers,
        json={"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"},
    )
    conflict = client.post(
        "/api/v1/evaluation/sessions",
        headers=headers,
        json={"scenario_id": "reducer_gear_alarm_v1", "locale": "en-US"},
    )
    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_invalid_or_missing_idempotency_key_maps_to_400(client):
    payload = {"scenario_id": "reducer_gear_alarm_v1"}
    missing = client.post("/api/v1/evaluation/sessions", headers=AUTH_HEADERS, json=payload)
    short = client.post(
        "/api/v1/evaluation/sessions",
        headers={**AUTH_HEADERS, "Idempotency-Key": "short"},
        json=payload,
    )
    invalid_scenario = client.post(
        "/api/v1/evaluation/sessions",
        headers={**AUTH_HEADERS, "Idempotency-Key": "invalid-scenario"},
        json={"scenario_id": "unknown"},
    )
    for response in (missing, short, invalid_scenario):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_five_concurrent_sessions_are_isolated(app):
    with TestClient(app) as local_client:
        def create(index: int) -> dict:
            response = local_client.post(
                "/api/v1/evaluation/sessions",
                headers={**AUTH_HEADERS, "Idempotency-Key": f"concurrent-{index:03d}"},
                json={"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"},
            )
            assert response.status_code == 201, response.text
            return response.json()["data"]

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(create, range(5)))

    assert len({item["evaluation_session_id"] for item in results}) == 5
    assert len({item["conversation_id"] for item in results}) == 5
    assert len({item["task_id"] for item in results}) == 5
    assert {item["task_state"] for item in results} == {"ALARM_RECEIVED"}
    assert all(app.state.repository.count_alarm_events(item["task_id"]) == 1 for item in results)
