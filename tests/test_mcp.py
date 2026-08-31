from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from conftest import AUTH_HEADERS, LIMITED_HEADERS, make_settings
from fastapi.testclient import TestClient

from zifisense_agent_api.main import create_app

MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
EXPECTED_TOOLS = {
    "create_evaluation_session",
    "list_assets",
    "list_current_faults",
    "get_fault_detail",
    "list_fault_history",
    "agent_invoke",
    "get_task",
    "get_monitoring_summary",
    "get_operating_context",
    "get_maintenance_history",
    "compare_peer_assets",
    "request_field_measurement",
    "ingest_field_measurement_result",
    "draft_work_order",
    "decide_work_order_approval",
    "ingest_work_order_completion",
    "ingest_alarm",
}


def modern_meta() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def modern_headers(method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        **AUTH_HEADERS,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MODERN_VERSION,
        "Mcp-Method": method,
        "X-Client-Id": "competition-evaluator",
    }
    if name:
        headers["Mcp-Name"] = name
    return headers


def modern_request(
    method: str,
    *,
    request_id: int = 1,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = modern_meta()
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def first_sse_message(response) -> dict[str, Any]:
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"SSE response contained no data event: {response.text}")


def call_modern_tool(
    client: TestClient,
    name: str,
    arguments: dict[str, Any],
    request_id: int = 1,
) -> tuple[Any, dict[str, Any]]:
    response = client.post(
        "/mcp",
        headers=modern_headers("tools/call", name),
        json=modern_request(
            "tools/call",
            request_id=request_id,
            params={"name": name, "arguments": arguments},
        ),
    )
    return response, response.json()


def test_mcp_requires_bearer_and_scope(app):
    request = modern_request("server/discover")
    base_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MODERN_VERSION,
        "Mcp-Method": "server/discover",
    }
    with TestClient(app) as client:
        missing = client.post("/mcp", headers=base_headers, json=request)
        invalid = client.post(
            "/mcp",
            headers={**base_headers, "Authorization": "Bearer invalid"},
            json=request,
        )
        limited = client.post(
            "/mcp",
            headers={**base_headers, **LIMITED_HEADERS},
            json=request,
        )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert limited.status_code == 403


def test_three_configured_accounts_can_discover_mcp(tmp_path):
    keys = ["configured-mcp-key-1", "configured-mcp-key-2", "configured-mcp-key-3"]
    records = [
        {
            "client_id": f"zifisense-mcp-{index}",
            "api_key_hash": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "scopes": ["mcp:use"],
        }
        for index, key in enumerate(keys, start=1)
    ]
    settings = make_settings(
        tmp_path,
        api_clients_json=json.dumps(records, separators=(",", ":")),
    )
    application = create_app(settings)
    request = modern_request("server/discover")
    base_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MODERN_VERSION,
        "Mcp-Method": "server/discover",
    }

    try:
        with TestClient(application) as client:
            responses = [
                client.post(
                    "/mcp",
                    headers={**base_headers, "Authorization": f"Bearer {key}"},
                    json=request,
                )
                for key in keys
            ]
        assert all(response.status_code == 200 for response in responses)
        assert all(
            response.json()["result"]["supportedVersions"] == [MODERN_VERSION]
            for response in responses
        )
    finally:
        application.state.database.close()


def test_configured_mcp_accounts_have_isolated_sessions_and_idempotency(tmp_path):
    keys = ["isolated-mcp-key-a", "isolated-mcp-key-b"]
    records = [
        {
            "client_id": f"isolated-client-{suffix}",
            "api_key_hash": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "scopes": ["mcp:use"],
        }
        for suffix, key in zip(("a", "b"), keys, strict=True)
    ]
    application = create_app(
        make_settings(
            tmp_path,
            api_clients_json=json.dumps(records, separators=(",", ":")),
        )
    )

    def call_as(
        client: TestClient,
        key: str,
        name: str,
        arguments: dict[str, Any],
        request_id: int,
    ):
        return client.post(
            "/mcp",
            headers={
                **modern_headers("tools/call", name),
                "Authorization": f"Bearer {key}",
            },
            json=modern_request(
                "tools/call",
                request_id=request_id,
                params={"name": name, "arguments": arguments},
            ),
        )

    try:
        with TestClient(application) as client:
            created = [
                call_as(
                    client,
                    key,
                    "create_evaluation_session",
                    {
                        "scenario_id": "reducer_gear_alarm_v1",
                        "idempotency_key": "shared-idempotency-key",
                    },
                    index + 1,
                )
                for index, key in enumerate(keys)
            ]
            payloads = [
                response.json()["result"]["structuredContent"]["data"]
                for response in created
            ]
            assert payloads[0]["evaluation_session_id"] != payloads[1]["evaluation_session_id"]

            own = call_as(
                client,
                keys[0],
                "get_task",
                {
                    "evaluation_session_id": payloads[0]["evaluation_session_id"],
                    "task_id": payloads[0]["task_id"],
                },
                10,
            ).json()
            cross_account = call_as(
                client,
                keys[1],
                "get_task",
                {
                    "evaluation_session_id": payloads[0]["evaluation_session_id"],
                    "task_id": payloads[0]["task_id"],
                },
                11,
            ).json()

        assert own["result"]["isError"] is False
        assert cross_account["result"]["isError"] is True
        assert "forbidden" in cross_account["result"]["content"][0]["text"].casefold()
    finally:
        application.state.database.close()


def test_modern_discovery_and_tool_catalog(app):
    with TestClient(app) as client:
        discovery = client.post(
            "/mcp",
            headers=modern_headers("server/discover"),
            json=modern_request("server/discover"),
        )
        tools = client.post(
            "/mcp",
            headers=modern_headers("tools/list"),
            json=modern_request("tools/list", request_id=2),
        )

    assert discovery.status_code == 200
    assert discovery.headers["content-type"].startswith("application/json")
    assert "mcp-session-id" not in discovery.headers
    discovered = discovery.json()["result"]
    assert discovered["supportedVersions"] == [MODERN_VERSION]
    assert discovered["capabilities"]["tools"] is not None

    assert tools.status_code == 200
    definitions = tools.json()["result"]["tools"]
    assert {tool["name"] for tool in definitions} == EXPECTED_TOOLS
    assert all(tool["inputSchema"]["type"] == "object" for tool in definitions)
    assert all("ctx" not in tool["inputSchema"].get("properties", {}) for tool in definitions)
    list_assets = next(tool for tool in definitions if tool["name"] == "list_assets")
    assert list_assets["inputSchema"]["properties"]["limit"]["maximum"] == 100


def test_legacy_initialize_and_sse_tools_list(app):
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LEGACY_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "legacy-pytest", "version": "1.0.0"},
        },
    }
    headers = {
        **AUTH_HEADERS,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(app) as client:
        initialized = client.post("/mcp", headers=headers, json=initialize)
        assert initialized.status_code == 200
        assert initialized.headers["content-type"].startswith("text/event-stream")
        assert "mcp-session-id" not in initialized.headers
        init_message = first_sse_message(initialized)
        assert init_message["result"]["protocolVersion"] == LEGACY_VERSION

        tools = client.post(
            "/mcp",
            headers={
                **headers,
                "MCP-Protocol-Version": LEGACY_VERSION,
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
    listed = first_sse_message(tools)
    assert {tool["name"] for tool in listed["result"]["tools"]} == EXPECTED_TOOLS


def test_asset_and_fault_query_story(app):
    with TestClient(app) as client:
        assets_response, assets_body = call_modern_tool(
            client,
            "list_assets",
            {"line_id": "LINE-ECOAT-01", "has_active_fault": True},
        )
        assets = assets_body["result"]["structuredContent"]
        assert assets_response.status_code == 200
        assert assets["total"] == 4
        assert all(item["line_id"] == "LINE-ECOAT-01" for item in assets["items"])
        assert all(item["active_fault_count"] > 0 for item in assets["items"])
        assert assets["is_simulated"] is True

        faults_response, faults_body = call_modern_tool(
            client,
            "list_current_faults",
            {"asset_id": "ASSET-REDUCER-001"},
            request_id=2,
        )
        faults = faults_body["result"]["structuredContent"]
        assert faults_response.status_code == 200
        assert faults["total"] == 1
        assert faults["items"][0]["fault_id"] == "FLT-20260820-001"
        assert faults["items"][0]["diagnosis_source"] == "PREDICTIVE_MAINTENANCE_SIMULATOR"

        detail_response, detail_body = call_modern_tool(
            client,
            "get_fault_detail",
            {"fault_id": "FLT-20260820-001"},
            request_id=3,
        )
        detail = detail_body["result"]["structuredContent"]
        assert detail_response.status_code == 200
        assert detail["diagnosis"]["professional_diagnosis"]["algorithm_version"]
        assert detail["diagnosis"]["confirmed_facts"][0]["evidence_id"]
        assert detail["diagnosis"]["agent_inferences"][0]["supporting_evidence_ids"]
        assert detail["diagnosis"]["limitations"]
        assert detail["is_simulated"] is True

        history_response, history_body = call_modern_tool(
            client,
            "list_fault_history",
            {"asset_id": "ASSET-REDUCER-001", "related_to_fault_id": "FLT-20260820-001"},
            request_id=4,
        )
        history = history_body["result"]["structuredContent"]
        assert history_response.status_code == 200
        assert {item["diagnosis_status"] for item in history["items"]} == {
            "VALIDATED",
            "REJECTED",
            "INCONCLUSIVE",
        }
        assert all(item["similarity"]["matched_dimensions"] for item in history["items"])
        assert all(item["similarity"]["differences"] for item in history["items"])


def test_every_current_fault_has_diagnosis_and_analysis(app):
    with TestClient(app) as client:
        _, list_body = call_modern_tool(client, "list_current_faults", {})
        faults = list_body["result"]["structuredContent"]["items"]
        assert len(faults) == 6
        for index, fault in enumerate(faults, start=2):
            response, detail_body = call_modern_tool(
                client,
                "get_fault_detail",
                {"fault_id": fault["fault_id"]},
                request_id=index,
            )
            detail = detail_body["result"]["structuredContent"]
            assert response.status_code == 200
            assert detail["diagnosis"]["professional_diagnosis"]["source_system"]
            assert detail["diagnosis"]["analysis_summary"]
            assert detail["diagnosis"]["limitations"]
            assert detail["evidence"]
            assert detail["open_questions"]


def test_investigation_tools_return_structured_source_backed_results(app):
    expectations = {
        "get_monitoring_summary": ("overall_status", "ANOMALOUS"),
        "get_operating_context": ("source_system", "MES_SIMULATOR"),
        "get_maintenance_history": ("source_system", "EAM_SIMULATOR"),
        "compare_peer_assets": ("comparability", "PARTIAL"),
    }
    with TestClient(app) as client:
        for index, (tool_name, (field, expected)) in enumerate(expectations.items(), start=1):
            response, body = call_modern_tool(
                client,
                tool_name,
                {"fault_id": "FLT-20260820-001"},
                request_id=index,
            )
            result = body["result"]["structuredContent"]
            assert response.status_code == 200
            assert result[field] == expected
            assert result["fault_id"] == "FLT-20260820-001"
            assert result["evidence_id"]
            assert result["is_simulated"] is True


def test_mcp_and_rest_share_session_task_and_agent(app):
    with TestClient(app) as client:
        _, created_body = call_modern_tool(
            client,
            "create_evaluation_session",
            {
                "scenario_id": "reducer_gear_alarm_v1",
                "idempotency_key": "mcp-shared-session-001",
            },
        )
        created = created_body["result"]["structuredContent"]["data"]
        _, task_body = call_modern_tool(
            client,
            "get_task",
            {
                "evaluation_session_id": created["evaluation_session_id"],
                "task_id": created["task_id"],
            },
            request_id=2,
        )
        task = task_body["result"]["structuredContent"]
        assert task["task_state"] == "ALARM_RECEIVED"
        assert task["alarm"]["alarm_id"] == "ALM-20260820-154429"

        rest = client.post(
            "/api/v1/agent/invoke",
            headers=AUTH_HEADERS,
            json={
                "evaluation_session_id": created["evaluation_session_id"],
                "conversation_id": created["conversation_id"],
                "task_id": created["task_id"],
                "message": "当前设备发生了什么？",
                "locale": "zh-CN",
            },
        )
        _, invoked_body = call_modern_tool(
            client,
            "agent_invoke",
            {
                "evaluation_session_id": created["evaluation_session_id"],
                "conversation_id": created["conversation_id"],
                "task_id": created["task_id"],
                "message": "当前设备发生了什么？",
            },
            request_id=3,
        )
        _, replay_body = call_modern_tool(
            client,
            "get_task",
            {
                "evaluation_session_id": created["evaluation_session_id"],
                "task_id": created["task_id"],
            },
            request_id=4,
        )
    assert rest.status_code == 200
    mcp_agent = invoked_body["result"]["structuredContent"]["response"]
    assert mcp_agent["data"]["system_diagnosis"] == rest.json()["data"]["system_diagnosis"]
    assert rest.json()["data"]["task_state"] == "CONTEXT_COLLECTING"
    assert mcp_agent["data"]["task_state"] == "EVIDENCE_REVIEW"
    replay = replay_body["result"]["structuredContent"]
    assert len(replay["conversation_turns"]) == 2
    assert replay["conversation_turns"][0]["tool_names"]


def test_ten_concurrent_modern_tool_calls(app):
    with TestClient(app) as client:

        def invoke(index: int) -> int:
            response, body = call_modern_tool(
                client,
                "list_assets",
                {"limit": 2},
                request_id=index + 1,
            )
            assert body["result"]["structuredContent"]["total"] == 12
            return response.status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(executor.map(invoke, range(10)))
    assert statuses == [200] * 10


def test_mcp_rate_limit_returns_retry_after(tmp_path):
    app = create_app(make_settings(tmp_path, rate_limit_mcp_per_minute=1))
    request = modern_request("server/discover")
    with TestClient(app) as client:
        first = client.post("/mcp", headers=modern_headers("server/discover"), json=request)
        limited = client.post("/mcp", headers=modern_headers("server/discover"), json=request)
    app.state.database.close()
    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "1"
