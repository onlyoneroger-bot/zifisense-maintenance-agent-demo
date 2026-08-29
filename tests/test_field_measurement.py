from __future__ import annotations

from conftest import AUTH_HEADERS, create_evaluation


def agent_payload(data: dict, message: str) -> dict:
    return {
        "evaluation_session_id": data["evaluation_session_id"],
        "conversation_id": data["conversation_id"],
        "task_id": data["task_id"],
        "message": message,
        "locale": "zh-CN",
    }


def field_event(data: dict, event_id: str, quality: str = "PASS") -> dict:
    return {
        "event_id": event_id,
        "event_type": "FIELD_MEASUREMENT_COMPLETED",
        "source_system": "PORTABLE_ANALYSIS_SIMULATOR",
        "occurred_at": "2026-08-29T10:30:00+08:00",
        "evaluation_session_id": data["evaluation_session_id"],
        "task_id": data["task_id"],
        "payload": {
            "asset_id": "ASSET-REDUCER-001",
            "measurement_point_id": "MP-4F040B86-X",
            "collection_quality": quality,
            "operating_condition": "负荷 80%，转速 1480 rpm",
            "sound_analysis": {"status": "ABNORMAL", "summary": "存在周期冲击"},
            "vibration_analysis": {
                "status": "ABNORMAL",
                "summary": "啮合频率边带升高",
            },
        },
    }


def test_agent_requires_explicit_consent_and_deduplicates_request(client, app):
    data = create_evaluation(client, "field-consent")
    suggestion = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(data, "是否需要现场补测？"),
    )
    assert suggestion.status_code == 200
    assert app.state.repository.get_field_measurement_request(data["task_id"]) is None

    consent = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(data, "同意补测，请现场安排补测。"),
    )
    duplicate = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(data, "可以补测。"),
    )

    assert consent.json()["data"]["task_state"] == "FIELD_EVIDENCE_PENDING"
    assert "明确同意" in consent.json()["data"]["answer"]
    first_tool = next(
        item
        for item in consent.json()["data"]["tool_executions"]
        if item["tool_name"] == "request_field_measurement"
    )
    duplicate_tool = next(
        item
        for item in duplicate.json()["data"]["tool_executions"]
        if item["tool_name"] == "request_field_measurement"
    )
    assert first_tool["status"] == "SUCCEEDED"
    assert duplicate_tool["status"] == "SKIPPED"


def test_field_result_requires_prior_request(client):
    data = create_evaluation(client, "field-no-consent")
    response = client.post(
        "/api/v1/events",
        headers=AUTH_HEADERS,
        json=field_event(data, "evt-no-consent"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_pass_field_result_is_idempotent_and_advances_state(client, app):
    data = create_evaluation(client, "field-pass")
    client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(data, "同意补测。"),
    )
    event = field_event(data, "evt-field-pass")
    first = client.post("/api/v1/events", headers=AUTH_HEADERS, json=event)
    duplicate = client.post("/api/v1/events", headers=AUTH_HEADERS, json=event)

    assert first.status_code == 200
    assert first.json()["data"] == {
        "event_id": "evt-field-pass",
        "accepted": True,
        "task_id": data["task_id"],
        "task_state": "HUMAN_DECISION",
        "duplicate": False,
    }
    assert duplicate.json()["data"]["duplicate"] is True
    assert len(app.state.repository.list_field_measurement_events(data["task_id"])) == 1
    _, task, _ = app.state.repository.get_task_snapshot(
        data["evaluation_session_id"], data["task_id"]
    )
    assert task.evidence_version == 2

    review = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(data, "现场补测结果如何？"),
    )
    review_data = review.json()["data"]
    assert "质量合格" in review_data["answer"]
    portable = [
        item
        for item in review_data["evidence"]
        if item["evidence_type"] == "PORTABLE_MEASUREMENT"
    ]
    assert len(portable) == 1
    assert portable[0]["quality_status"] == "VALID"
    assert portable[0]["usage_level"] == "DECISION_REFERENCE"
    assert any(
        item["tool_name"] == "read_field_measurement_results"
        for item in review_data["tool_executions"]
    )


def test_event_id_replay_with_changed_payload_is_conflict(client):
    data = create_evaluation(client, "field-idempotency-conflict")
    client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(data, "同意补测。"),
    )
    event = field_event(data, "evt-field-conflict")
    first = client.post("/api/v1/events", headers=AUTH_HEADERS, json=event)
    event["payload"]["vibration_analysis"]["summary"] = "不同结果"
    conflict = client.post("/api/v1/events", headers=AUTH_HEADERS, json=event)
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_partial_and_failed_results_remain_pending(client, app):
    for quality in ("PARTIAL", "FAIL"):
        data = create_evaluation(client, f"field-{quality.lower()}")
        client.post(
            "/api/v1/agent/invoke",
            headers=AUTH_HEADERS,
            json=agent_payload(data, "允许补测。"),
        )
        response = client.post(
            "/api/v1/events",
            headers=AUTH_HEADERS,
            json=field_event(data, f"evt-{quality.lower()}", quality),
        )
        assert response.json()["data"]["task_state"] == "FIELD_EVIDENCE_PENDING"
        request = app.state.repository.get_field_measurement_request(data["task_id"])
        assert request.status == "RETRY_REQUIRED"


def test_field_result_rejects_wrong_asset_and_cross_session(client):
    first = create_evaluation(client, "field-first")
    second = create_evaluation(client, "field-second")
    client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=agent_payload(first, "同意补测。"),
    )
    wrong_asset = field_event(first, "evt-wrong-asset")
    wrong_asset["payload"]["asset_id"] = "ASSET-OTHER"
    asset_response = client.post(
        "/api/v1/events", headers=AUTH_HEADERS, json=wrong_asset
    )
    cross_session = field_event(first, "evt-cross-session")
    cross_session["evaluation_session_id"] = second["evaluation_session_id"]
    session_response = client.post(
        "/api/v1/events", headers=AUTH_HEADERS, json=cross_session
    )
    assert asset_response.status_code == 400
    assert session_response.status_code == 403
