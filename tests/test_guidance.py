from __future__ import annotations

from fastapi.testclient import TestClient
from test_mcp import (
    EXPECTED_TOOLS,
    call_modern_tool,
    modern_headers,
    modern_request,
)

READ_ONLY_TOOLS = {
    "list_assets",
    "list_current_faults",
    "get_fault_detail",
    "list_fault_history",
    "get_monitoring_summary",
    "get_operating_context",
    "get_maintenance_history",
    "compare_peer_assets",
    "get_task",
}


def structured(client: TestClient, name: str, arguments: dict, request_id: int = 1) -> dict:
    response, body = call_modern_tool(client, name, arguments, request_id=request_id)
    assert response.status_code == 200, response.text
    assert "error" not in body, body
    result = body["result"]["structuredContent"]
    assert result["guidance"]["summary"]
    assert result["guidance"]["next_steps"]
    assert result["guidance"]["constraints"]
    return result


def test_all_tools_publish_actionable_metadata(app):
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers=modern_headers("tools/list"),
            json=modern_request("tools/list"),
        )
    tools = response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool["title"]
        assert len(tool["description"]) >= 24
        annotations = tool["annotations"]
        assert annotations["openWorldHint"] is False
        assert annotations["destructiveHint"] is False
        assert annotations["readOnlyHint"] is (tool["name"] in READ_ONLY_TOOLS)
    approval = next(tool for tool in tools if tool["name"] == "decide_work_order_approval")
    assert approval["annotations"]["idempotentHint"] is False


def test_catalog_queries_have_different_guidance_profiles(app):
    with TestClient(app) as client:
        assets = structured(client, "list_assets", {"has_active_fault": True})
        faults = structured(client, "list_current_faults", {})
        fault_id = faults["items"][0]["fault_id"]
        detail = structured(client, "get_fault_detail", {"fault_id": fault_id})
        history = structured(
            client,
            "list_fault_history",
            {"related_to_fault_id": fault_id},
        )
        monitoring = structured(client, "get_monitoring_summary", {"fault_id": fault_id})
        context = structured(client, "get_operating_context", {"fault_id": fault_id})
        maintenance = structured(client, "get_maintenance_history", {"fault_id": fault_id})
        peers = structured(client, "compare_peer_assets", {"fault_id": fault_id})

    assert assets["guidance"]["profile"] == "NAVIGATION"
    assert faults["guidance"]["urgency"] == "CRITICAL"
    assert detail["guidance"]["actionability"] == "DECISION_PENDING"
    assert detail["guidance"]["blocking_questions"]
    assert history["guidance"]["current_stage"] == "HISTORICAL_COMPARISON"
    assert monitoring["guidance"]["current_stage"] == "TREND_VERIFICATION"
    assert context["guidance"]["current_stage"] == "CONTEXT_COMPLETION"
    assert maintenance["guidance"]["current_stage"] == "MAINTENANCE_CORRELATION"
    assert peers["guidance"]["current_stage"] == "PEER_COMPARISON"
    summaries = {
        result["guidance"]["summary"] for result in (monitoring, context, maintenance, peers)
    }
    assert len(summaries) == 4


def test_all_catalog_faults_can_enter_an_isolated_session(app):
    with TestClient(app) as client:
        faults = structured(client, "list_current_faults", {})["items"]
        for index, fault in enumerate(faults, start=1):
            created = structured(
                client,
                "create_evaluation_session",
                {
                    "fault_id": fault["fault_id"],
                    "idempotency_key": f"catalog-guidance-{index:02d}",
                },
                request_id=index + 10,
            )
            assert created["data"]["scenario_id"] == f"catalog_fault:{fault['fault_id']}"
            assert created["data"]["task_state"] == "ALARM_RECEIVED"


def test_safety_question_is_decision_support_without_control_side_effect(app):
    with TestClient(app) as client:
        created = structured(
            client,
            "create_evaluation_session",
            {
                "fault_id": "FLT-20260820-002",
                "idempotency_key": "critical-safety-session",
            },
        )["data"]
        invoked = structured(
            client,
            "agent_invoke",
            {
                "evaluation_session_id": created["evaluation_session_id"],
                "conversation_id": created["conversation_id"],
                "task_id": created["task_id"],
                "message": "这台泵是否需要停机？请说明依据和处置顺序。",
            },
            request_id=2,
        )
        task = structured(
            client,
            "get_task",
            {
                "evaluation_session_id": created["evaluation_session_id"],
                "task_id": created["task_id"],
            },
            request_id=3,
        )

    response = invoked["response"]["data"]
    assert "企业 SOP" in response["answer"]
    assert "不具备也不会调用生产控制能力" in response["answer"]
    assert [item["code"] for item in response["recommended_actions"]] == [
        "VERIFY_LIVE_SAFETY_CONTEXT",
        "APPLY_ENTERPRISE_SOP",
    ]
    assert all(
        item["tool_name"] not in {"plc_control", "dcs_control", "stop_asset"}
        for item in response["tool_executions"]
    )
    assert task["conversation_turns"][-1]["intent"] == "SAFETY_DECISION"


def test_write_workflow_returns_state_specific_guidance(app):
    with TestClient(app) as client:
        created = structured(
            client,
            "create_evaluation_session",
            {
                "scenario_id": "reducer_gear_alarm_v1",
                "idempotency_key": "guidance-write-session",
            },
        )["data"]
        common = {
            "evaluation_session_id": created["evaluation_session_id"],
            "task_id": created["task_id"],
        }
        requested = structured(
            client,
            "request_field_measurement",
            {**common, "consent": True},
            request_id=2,
        )
        measured = structured(
            client,
            "ingest_field_measurement_result",
            {
                **common,
                "event_id": "evt-guidance-field-pass",
                "asset_id": "ASSET-REDUCER-001",
                "measurement_point_id": "MP-4F040B86-X",
                "collection_quality": "PASS",
                "sound_analysis": {"summary": "存在周期冲击"},
                "vibration_analysis": {"summary": "啮合频率边带升高"},
            },
            request_id=3,
        )
        draft = structured(
            client,
            "draft_work_order",
            {
                **common,
                "conversation_id": created["conversation_id"],
            },
            request_id=4,
        )
        pending = draft["data"]["pending_approval"]
        approved = structured(
            client,
            "decide_work_order_approval",
            {
                "task_id": created["task_id"],
                "approval_id": pending["approval_id"],
                "approval_challenge": pending["approval_challenge"],
                "decision": "APPROVE",
                "evidence_version": pending["evidence_version"],
            },
            request_id=5,
        )
        completed = structured(
            client,
            "ingest_work_order_completion",
            {
                **common,
                "event_id": "evt-guidance-work-complete",
                "work_order_id": approved["data"]["work_order_id"],
                "actual_fault": "齿轮啮合面磨损",
                "inspection_findings": "发现局部点蚀",
                "actions_taken": ["更换齿轮组", "复测振动"],
                "parts_replaced": ["齿轮组"],
                "post_maintenance_diagnosis": {
                    "improved": True,
                    "summary": "维修后趋势恢复",
                },
            },
            request_id=6,
        )

    assert requested["guidance"]["current_stage"] == "FIELD_EVIDENCE_PENDING"
    assert measured["guidance"]["actionability"] == "DECISION_PENDING"
    assert draft["guidance"]["actionability"] == "APPROVAL_REQUIRED"
    assert approved["guidance"]["current_stage"] == "WORK_ORDER_APPROVED"
    assert completed["guidance"]["current_stage"] == "POST_MAINTENANCE_VALIDATION"
