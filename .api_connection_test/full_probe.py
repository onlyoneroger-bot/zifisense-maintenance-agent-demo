from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_URL = os.getenv("MCP_PROBE_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
TOKEN = os.getenv("MCP_API_KEY", "dev-evaluator-key")
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
OUTPUT_DIR = Path(
    os.getenv(
        "MCP_PROBE_OUTPUT_DIR",
        str(Path(__file__).resolve().parent / "full_probe_reports"),
    )
)
RUN_SUFFIX = uuid.uuid4().hex[:12]


@dataclass
class Check:
    category: str
    name: str
    passed: bool
    status: int | None
    elapsed_ms: int
    detail: str


checks: list[Check] = []
request_id = 0


def record(
    category: str,
    name: str,
    passed: bool,
    status: int | None,
    elapsed_ms: int,
    detail: str,
) -> None:
    checks.append(Check(category, name, passed, status, elapsed_ms, detail))
    marker = "PASS" if passed else "FAIL"
    print(f"[{marker}] {category}: {name} ({elapsed_ms} ms) - {detail}")


def parse_payload(raw: bytes, content_type: str) -> Any:
    text = raw.decode("utf-8") if raw else ""
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            if line.startswith("data: "):
                return json.loads(line.removeprefix("data: "))
        raise AssertionError("SSE response contained no data event")
    return json.loads(text) if text else None


def http(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    authenticated: bool = True,
) -> tuple[int, dict[str, str], Any, int]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    if authenticated:
        request_headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=request_headers, method=method
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        response_headers = dict(error.headers.items())
        raw = error.read()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    content_type = next(
        (value for key, value in response_headers.items() if key.lower() == "content-type"), ""
    )
    return status, response_headers, parse_payload(raw, content_type), elapsed_ms


def rest_check(
    name: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
    predicate: Any = None,
    authenticated: bool = True,
) -> Any:
    status, _, payload, elapsed = http(
        method, path, body=body, headers=headers, authenticated=authenticated
    )
    passed = status == expected_status and (predicate(payload) if predicate else True)
    detail = f"HTTP {status}; expected {expected_status}"
    record("REST", name, passed, status, elapsed, detail)
    if not passed:
        raise AssertionError(f"{name}: {detail}; body={payload}")
    return payload


def modern_mcp(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    tool_name: str | None = None,
) -> tuple[int, dict[str, str], Any, int]:
    global request_id
    request_id += 1
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": "api-mcp-full-probe",
            "version": "1.0.0",
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MODERN_VERSION,
        "Mcp-Method": method,
        "X-Client-Id": "api-mcp-full-probe",
    }
    if tool_name:
        headers["Mcp-Name"] = tool_name
    return http(
        "POST",
        "/mcp",
        headers=headers,
        body={"jsonrpc": "2.0", "id": request_id, "method": method, "params": request_params},
    )


def tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    status, _, payload, elapsed = modern_mcp(
        "tools/call", {"name": name, "arguments": arguments}, tool_name=name
    )
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    passed = status == 200 and result.get("isError") is False and "structuredContent" in result
    detail = f"HTTP {status}; isError={result.get('isError')}"
    record("MCP Tool", name, passed, status, elapsed, detail)
    if not passed:
        raise AssertionError(f"{name}: {detail}; body={payload}")
    return result["structuredContent"]


def field_payload(session: dict[str, Any], event_id: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "FIELD_MEASUREMENT_COMPLETED",
        "source_system": "PORTABLE_ANALYSIS_SIMULATOR",
        "occurred_at": "2026-08-30T10:00:00+08:00",
        "evaluation_session_id": session["evaluation_session_id"],
        "task_id": session["task_id"],
        "payload": {
            "asset_id": "ASSET-REDUCER-001",
            "measurement_point_id": "MP-4F040B86-X",
            "collection_quality": "PASS",
            "operating_condition": "负荷 80%，转速 1480 rpm",
            "sound_analysis": {"status": "ABNORMAL", "summary": "存在周期冲击"},
            "vibration_analysis": {"status": "ABNORMAL", "summary": "啮合频率边带明显"},
        },
    }


def create_rest_session(key: str) -> dict[str, Any]:
    response = rest_check(
        "POST /api/v1/evaluation/sessions",
        "POST",
        "/api/v1/evaluation/sessions",
        body={"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"},
        headers={"Idempotency-Key": key},
        expected_status=201,
        predicate=lambda item: bool(item.get("data", {}).get("task_id")),
    )
    return response["data"]


def rest_workflow() -> None:
    rest_check(
        "GET /health",
        "GET",
        "/health",
        authenticated=False,
        predicate=lambda item: item.get("status") == "ok" and item.get("version") == "1.0.0",
    )
    rest_check(
        "GET /api/v1/capabilities",
        "GET",
        "/api/v1/capabilities",
        predicate=lambda item: bool(item.get("data", {}).get("capabilities"))
        and bool(item.get("data", {}).get("safety_boundaries")),
    )
    session = create_rest_session(f"probe-rest-session-{RUN_SUFFIX}")
    invoke_body = {
        "evaluation_session_id": session["evaluation_session_id"],
        "conversation_id": session["conversation_id"],
        "task_id": session["task_id"],
        "message": "同意补测。",
        "locale": "zh-CN",
    }
    rest_check(
        "POST /api/v1/agent/invoke",
        "POST",
        "/api/v1/agent/invoke",
        body=invoke_body,
        predicate=lambda item: item.get("data", {}).get("task_state")
        == "FIELD_EVIDENCE_PENDING",
    )
    rest_check(
        "POST /api/v1/events",
        "POST",
        "/api/v1/events",
        body=field_payload(session, f"probe-rest-field-{RUN_SUFFIX}"),
        predicate=lambda item: item.get("data", {}).get("task_state") == "HUMAN_DECISION",
    )
    draft = rest_check(
        "POST /api/v1/agent/invoke (draft)",
        "POST",
        "/api/v1/agent/invoke",
        body={**invoke_body, "message": "生成工单草稿。"},
        predicate=lambda item: item.get("data", {}).get("task_state") == "APPROVAL_PENDING",
    )["data"]
    rest_check(
        "GET /api/v1/tasks/{task_id}",
        "GET",
        f"/api/v1/tasks/{session['task_id']}",
        predicate=lambda item: item.get("data", {}).get("pending_approval") is not None,
    )
    pending = draft["pending_approval"]
    approval = rest_check(
        "POST /api/v1/tasks/{task_id}/approvals",
        "POST",
        f"/api/v1/tasks/{session['task_id']}/approvals",
        headers={"Idempotency-Key": f"probe-rest-approval-{RUN_SUFFIX}"},
        body={
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "APPROVE",
            "evidence_version": pending["evidence_version"],
        },
        predicate=lambda item: item.get("data", {}).get("task_state")
        == "MAINTENANCE_PROCESSING",
    )
    assert approval["data"]["work_order_id"]
    rest_check(
        "POST /api/v1/admin/reset",
        "POST",
        "/api/v1/admin/reset",
        headers={"Idempotency-Key": f"probe-rest-reset-{RUN_SUFFIX}"},
        body={"scope": "SESSION", "evaluation_session_id": session["evaluation_session_id"]},
        predicate=lambda item: item.get("data", {}).get("status") == "COMPLETED",
    )


def mcp_protocol_checks() -> set[str]:
    status, headers, payload, elapsed = modern_mcp("server/discover")
    no_session = not any(key.lower() == "mcp-session-id" for key in headers)
    passed = (
        status == 200
        and payload.get("result", {}).get("supportedVersions") == [MODERN_VERSION]
        and no_session
    )
    record("MCP Protocol", "server/discover 2026-07-28", passed, status, elapsed, "stateless")
    if not passed:
        raise AssertionError(payload)

    status, _, payload, elapsed = modern_mcp("tools/list")
    definitions = payload.get("result", {}).get("tools", [])
    names = {item.get("name") for item in definitions}
    passed = status == 200 and len(names) == 17 and all(
        item.get("inputSchema", {}).get("type") == "object" for item in definitions
    )
    record("MCP Protocol", "tools/list", passed, status, elapsed, f"{len(names)} tools")
    if not passed:
        raise AssertionError(payload)

    initialize = {
        "jsonrpc": "2.0",
        "id": 900,
        "method": "initialize",
        "params": {
            "protocolVersion": LEGACY_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "api-mcp-full-probe", "version": "1.0.0"},
        },
    }
    status, headers, payload, elapsed = http(
        "POST",
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        body=initialize,
    )
    passed = (
        status == 200
        and payload.get("result", {}).get("protocolVersion") == LEGACY_VERSION
        and not any(key.lower() == "mcp-session-id" for key in headers)
    )
    record("MCP Protocol", "initialize 2025-11-25", passed, status, elapsed, "SSE compatible")
    if not passed:
        raise AssertionError(payload)
    return names


def mcp_workflow(discovered_names: set[str]) -> None:
    created = tool(
        "create_evaluation_session",
        {
            "scenario_id": "reducer_gear_alarm_v1",
            "idempotency_key": f"probe-mcp-session-{RUN_SUFFIX}",
            "locale": "zh-CN",
        },
    )
    session = created["data"]
    tool("list_assets", {"line_id": "LINE-ECOAT-01", "has_active_fault": True})
    tool("list_current_faults", {"asset_id": "ASSET-REDUCER-001"})
    tool("get_fault_detail", {"fault_id": "FLT-20260820-001"})
    tool(
        "list_fault_history",
        {"asset_id": "ASSET-REDUCER-001", "related_to_fault_id": "FLT-20260820-001"},
    )
    tool("get_monitoring_summary", {"fault_id": "FLT-20260820-001"})
    tool("get_operating_context", {"fault_id": "FLT-20260820-001"})
    tool("get_maintenance_history", {"fault_id": "FLT-20260820-001"})
    tool("compare_peer_assets", {"fault_id": "FLT-20260820-001"})

    agent = tool(
        "agent_invoke",
        {
            "evaluation_session_id": session["evaluation_session_id"],
            "conversation_id": session["conversation_id"],
            "task_id": session["task_id"],
            "message": "同意补测。",
            "locale": "zh-CN",
        },
    )
    assert agent["response"]["data"]["task_state"] == "FIELD_EVIDENCE_PENDING"
    tool(
        "request_field_measurement",
        {
            "evaluation_session_id": session["evaluation_session_id"],
            "task_id": session["task_id"],
            "consent": True,
        },
    )
    tool(
        "ingest_field_measurement_result",
        {
            "event_id": f"probe-mcp-field-{RUN_SUFFIX}",
            "evaluation_session_id": session["evaluation_session_id"],
            "task_id": session["task_id"],
            "asset_id": "ASSET-REDUCER-001",
            "measurement_point_id": "MP-4F040B86-X",
            "collection_quality": "PASS",
            "sound_analysis": {"status": "ABNORMAL", "summary": "存在周期冲击"},
            "vibration_analysis": {"status": "ABNORMAL", "summary": "啮合频率边带明显"},
            "operating_condition": "负荷 80%，转速 1480 rpm",
        },
    )
    draft = tool(
        "draft_work_order",
        {
            "evaluation_session_id": session["evaluation_session_id"],
            "conversation_id": session["conversation_id"],
            "task_id": session["task_id"],
        },
    )
    pending = draft["data"]["pending_approval"]
    approved = tool(
        "decide_work_order_approval",
        {
            "task_id": session["task_id"],
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "APPROVE",
            "evidence_version": pending["evidence_version"],
            "comment": "API/MCP 全量连通性验证",
        },
    )
    work_order_id = approved["data"]["work_order_id"]
    tool(
        "ingest_work_order_completion",
        {
            "event_id": f"probe-mcp-work-complete-{RUN_SUFFIX}",
            "evaluation_session_id": session["evaluation_session_id"],
            "task_id": session["task_id"],
            "work_order_id": work_order_id,
            "actual_fault": "齿轮啮合面磨损",
            "inspection_findings": "发现局部点蚀",
            "actions_taken": ["更换齿轮组", "复测振动"],
            "parts_replaced": ["齿轮组"],
            "post_maintenance_diagnosis": {"improved": True, "summary": "维修后复测通过"},
        },
    )
    snapshot = tool(
        "get_task",
        {
            "evaluation_session_id": session["evaluation_session_id"],
            "task_id": session["task_id"],
        },
    )
    assert snapshot["task_state"] == "CLOSED"
    tool(
        "ingest_alarm",
        {
            "event_id": f"probe-mcp-alarm-{RUN_SUFFIX}",
            "evaluation_session_id": session["evaluation_session_id"],
            "alarm_id": "ALARM-PROBE-MCP-001",
            "asset_id": "ASSET-REDUCER-001",
            "measurement_point_id": "MP-4F040B86-X",
            "severity": "WARNING",
            "diagnosis_text": "MCP 全量验证告警",
            "confidence": 0.73,
            "algorithm_version": "probe-v1",
            "evidence_features": [{"name": "rms", "value": 4.2}],
        },
    )

    called = {check.name for check in checks if check.category == "MCP Tool" and check.passed}
    missing = discovered_names - called
    if missing:
        raise AssertionError(f"Discovered but not successfully called: {sorted(missing)}")


def write_report(error: str | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    passed = sum(item.passed for item in checks)
    failed = len(checks) - passed
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": BASE_URL,
        "passed": failed == 0 and error is None,
        "summary": {"total": len(checks), "passed": passed, "failed": failed},
        "error": error,
        "checks": [asdict(item) for item in checks],
    }
    (OUTPUT_DIR / "full_probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# API/MCP 全量连通性报告",
        "",
        f"- 目标：`{BASE_URL}`",
        f"- 结果：**{'通过' if result['passed'] else '失败'}**",
        f"- 检查：{len(checks)}；通过：{passed}；失败：{failed}",
        "",
        "| 类别 | 检查 | 结果 | HTTP | 耗时 |",
        "|---|---|---|---:|---:|",
    ]
    for item in checks:
        lines.append(
            f"| {item.category} | {item.name} | {'PASS' if item.passed else 'FAIL'} | "
            f"{item.status if item.status is not None else '-'} | {item.elapsed_ms} ms |"
        )
    if error:
        lines.extend(["", "## 失败原因", "", f"`{error}`"])
    (OUTPUT_DIR / "full_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    error: str | None = None
    try:
        rest_workflow()
        discovered = mcp_protocol_checks()
        mcp_workflow(discovered)
    except Exception as exc:  # report the exact probe boundary that failed
        error = f"{type(exc).__name__}: {exc}"
        print(error, file=sys.stderr)
    finally:
        write_report(error)
    return 0 if error is None and all(item.passed for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
