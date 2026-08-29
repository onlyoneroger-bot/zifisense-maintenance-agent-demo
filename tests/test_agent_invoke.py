from pathlib import Path

import pytest
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


def test_agent_runs_controlled_multi_tool_fixture_investigation(client):
    data = create_evaluation(client)
    response = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["is_degraded"] is False
    assert body["data"]["task_state"] == "CONTEXT_COLLECTING"
    assert body["data"]["system_diagnosis"] == {
        "diagnosis_text": "齿轮故障/转子不平衡",
        "confidence": 0.82,
        "source_system": "PREDICTIVE_MAINTENANCE_SIMULATOR",
        "algorithm_version": "predictive-fixture-v1",
    }
    assert len(body["data"]["evidence"]) >= 4
    assert body["data"]["evidence"][0]["evidence_type"] == "ALARM"
    assert body["data"]["evidence"][0]["is_simulated"] is True
    assert body["data"]["citations"] == []
    assert {item["tool_name"] for item in body["data"]["tool_executions"]} == {
        "get_monitoring_summary",
        "get_operating_context",
        "get_maintenance_history",
        "compare_peer_assets",
    }
    assert body["data"]["agent_inferences"]
    assert all(
        item["supporting_evidence_ids"] for item in body["data"]["agent_inferences"]
    )
    assert body["data"]["pending_approval"] is None
    assert "专业候选诊断" in body["data"]["answer"]
    assert "不能替代现场确认" in body["data"]["answer"]


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


@pytest.mark.parametrize(
    ("message", "expected_tools"),
    [
        (
            "最近振动监测数据正常吗？",
            {"get_monitoring_summary", "get_operating_context"},
        ),
        (
            "这台设备以前发生过类似问题吗？",
            {"get_monitoring_summary", "list_fault_history"},
        ),
        (
            "查一下近期检修工单和维修记录",
            {"get_monitoring_summary", "get_maintenance_history"},
        ),
        (
            "同线其他设备有没有类似异常，帮我对比一下",
            {"get_monitoring_summary", "compare_peer_assets"},
        ),
        (
            "报警时的负荷、转速和工况怎么样？",
            {"get_monitoring_summary", "get_operating_context"},
        ),
    ],
)
def test_agent_routes_synonyms_to_registered_tools(client, message, expected_tools):
    data = create_evaluation(client, f"intent-{abs(hash(message))}")
    response = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data, message=message),
    )
    assert response.status_code == 200
    assert {
        item["tool_name"] for item in response.json()["data"]["tool_executions"]
    } == expected_tools


def test_human_context_is_unverified_deduplicated_and_persisted(client, app):
    data = create_evaluation(client, "human-context-session")
    overview = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data),
    )
    claim_text = "近期负荷提高了20%，昨天还刚调整过配方。"
    claim = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data, message=claim_text),
    )
    duplicate = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data, message=claim_text),
    )

    assert overview.json()["data"]["task_state"] == "CONTEXT_COLLECTING"
    assert claim.json()["data"]["task_state"] == "EVIDENCE_REVIEW"
    human_evidence = [
        item
        for item in claim.json()["data"]["evidence"]
        if item["evidence_type"] == "HUMAN_CLAIM"
    ]
    assert len(human_evidence) == 1
    assert human_evidence[0]["quality_status"] == "UNVERIFIED"
    assert human_evidence[0]["usage_level"] == "RECORD_ONLY"
    assert claim_text not in {
        fact["text"] for fact in claim.json()["data"]["confirmed_facts"]
    }
    duplicate_record = next(
        item
        for item in duplicate.json()["data"]["tool_executions"]
        if item["tool_name"] == "record_human_input"
    )
    assert duplicate_record["status"] == "SKIPPED"
    assert len(app.state.repository.list_human_claims(data["task_id"])) == 1
    assert len(app.state.repository.list_conversation_turns(data["task_id"])) == 3


def test_out_of_scope_request_returns_menu_without_state_change(client, app):
    data = create_evaluation(client, "out-of-scope-session")
    response = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json=invoke_payload(data, message="帮我写一篇公司新闻稿"),
    )
    body = response.json()["data"]
    assert response.status_code == 200
    assert body["task_state"] == "ALARM_RECEIVED"
    assert body["tool_executions"] == []
    assert "不属于设备智能运维范围" in body["answer"]
    assert len(app.state.repository.list_conversation_turns(data["task_id"])) == 1


def test_three_round_judge_investigation_is_replayable(client, app):
    data = create_evaluation(client, "three-round-judge-story")
    messages = [
        "描述一下这个设备的异常，并分析近期监测数据。",
        "近期负荷提高了20%，昨天还刚调整过配方。",
        "同线其他设备的数据是否也有异常？",
    ]

    responses = [
        client.post(
            "/api/v1/agent/invoke",
            headers=AUTH_HEADERS,
            json=invoke_payload(data, message=message),
        )
        for message in messages
    ]

    assert all(response.status_code == 200 for response in responses)
    assert [response.json()["data"]["task_state"] for response in responses] == [
        "CONTEXT_COLLECTING",
        "EVIDENCE_REVIEW",
        "EVIDENCE_REVIEW",
    ]
    second_evidence = responses[1].json()["data"]["evidence"]
    assert any(
        item["evidence_type"] == "HUMAN_CLAIM"
        and item["quality_status"] == "UNVERIFIED"
        for item in second_evidence
    )
    assert {
        item["tool_name"]
        for item in responses[2].json()["data"]["tool_executions"]
    } == {"get_monitoring_summary", "compare_peer_assets"}

    turns = app.state.repository.list_conversation_turns(data["task_id"])
    assert [turn.intent for turn in turns] == [
        "MONITORING",
        "HUMAN_CONTEXT",
        "PEER_COMPARISON",
    ]
    assert [turn.message for turn in turns] == messages
    assert len(app.state.repository.list_human_claims(data["task_id"])) == 1
