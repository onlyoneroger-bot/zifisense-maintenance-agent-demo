from __future__ import annotations

from conftest import AUTH_HEADERS, create_evaluation
from test_openapi_contract import assert_schema


def alarm_event(data: dict, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "ALARM_RAISED",
        "source_system": "PREDICTIVE_MAINTENANCE_SIMULATOR",
        "occurred_at": "2026-08-29T09:00:00+08:00",
        "evaluation_session_id": data["evaluation_session_id"],
        "payload": {
            "alarm_id": "ALARM-NEW-001",
            "asset_id": "ASSET-REDUCER-001",
            "measurement_point_id": "MP-4F040B86-X",
            "severity": "WARNING",
            "diagnosis_text": "齿轮啮合异常候选",
            "confidence": 0.71,
            "algorithm_version": "predictive-fixture-v2",
            "evidence_features": [{"name": "rms", "value": 4.2}],
        },
    }


def test_alarm_event_creates_queryable_task_and_is_idempotent(client):
    data = create_evaluation(client, "alarm-event-session")
    event = alarm_event(data, "evt-alarm-new")
    first = client.post("/api/v1/events", headers=AUTH_HEADERS, json=event)
    duplicate = client.post("/api/v1/events", headers=AUTH_HEADERS, json=event)

    assert first.status_code == 200
    assert first.json()["data"]["task_state"] == "ALARM_RECEIVED"
    assert first.json()["data"]["duplicate"] is False
    assert duplicate.json()["data"]["duplicate"] is True
    task_id = first.json()["data"]["task_id"]
    snapshot = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH_HEADERS)
    assert snapshot.status_code == 200
    assert snapshot.json()["data"]["alarm"]["alarm_id"] == "ALARM-NEW-001"
    assert snapshot.json()["data"]["evidence_version"] == 1

    changed = alarm_event(data, "evt-alarm-new")
    changed["payload"]["diagnosis_text"] = "不同诊断"
    conflict = client.post("/api/v1/events", headers=AUTH_HEADERS, json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_session_reset_removes_only_target_session(client):
    target = create_evaluation(client, "reset-target-session")
    survivor = create_evaluation(client, "reset-survivor-session")
    response = client.post(
        "/api/v1/admin/reset",
        headers={**AUTH_HEADERS, "Idempotency-Key": "reset-one-session"},
        json={
            "scope": "SESSION",
            "evaluation_session_id": target["evaluation_session_id"],
        },
    )
    assert response.status_code == 200
    assert_schema(response.json(), "ResetResponse")
    assert response.json()["data"] == {
        "scope": "SESSION",
        "status": "COMPLETED",
        "reset_count": 1,
    }
    missing = client.get(f"/api/v1/tasks/{target['task_id']}", headers=AUTH_HEADERS)
    remaining = client.get(
        f"/api/v1/tasks/{survivor['task_id']}", headers=AUTH_HEADERS
    )
    assert missing.status_code == 404
    assert remaining.status_code == 200


def test_session_reset_requires_session_id(client):
    response = client.post(
        "/api/v1/admin/reset",
        headers={**AUTH_HEADERS, "Idempotency-Key": "reset-missing-session"},
        json={"scope": "SESSION"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
