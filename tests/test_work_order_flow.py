from __future__ import annotations

from conftest import AUTH_HEADERS, create_evaluation
from test_openapi_contract import assert_schema

from zifisense_agent_api.infrastructure.database import ApprovalRecord


def invoke(client, data: dict, message: str):
    return client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json={
            "evaluation_session_id": data["evaluation_session_id"],
            "conversation_id": data["conversation_id"],
            "task_id": data["task_id"],
            "message": message,
        },
    )


def field_event(data: dict, event_id: str) -> dict:
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
            "collection_quality": "PASS",
            "sound_analysis": {"summary": "周期冲击"},
            "vibration_analysis": {"summary": "啮合频率边带升高"},
        },
    }


def work_event(data: dict, work_order_id: str, event_id: str, improved: bool) -> dict:
    return {
        "event_id": event_id,
        "event_type": "WORK_ORDER_COMPLETED",
        "source_system": "EAM_SIMULATOR",
        "occurred_at": "2026-08-29T12:30:00+08:00",
        "evaluation_session_id": data["evaluation_session_id"],
        "task_id": data["task_id"],
        "payload": {
            "work_order_id": work_order_id,
            "actual_fault": "齿轮啮合面磨损",
            "inspection_findings": "发现局部点蚀",
            "actions_taken": ["更换齿轮组", "复测振动"],
            "parts_replaced": ["齿轮组"],
            "completed_at": "2026-08-29T12:20:00+08:00",
            "post_maintenance_diagnosis": {
                "improved": improved,
                "summary": "维修后复测",
            },
        },
    }


def prepare_approval(client, key: str) -> tuple[dict, dict]:
    data = create_evaluation(client, key)
    invoke(client, data, "同意补测。")
    field = client.post(
        "/api/v1/events",
        headers=AUTH_HEADERS,
        json=field_event(data, f"evt-{key}"),
    )
    assert field.status_code == 200
    draft = invoke(client, data, "生成工单草稿。")
    assert draft.status_code == 200
    pending = draft.json()["data"]["pending_approval"]
    assert draft.json()["data"]["task_state"] == "APPROVAL_PENDING"
    assert pending["impact_preview"]["production_write"] is False
    return data, pending


def test_task_snapshot_and_approval_security(client):
    data, pending = prepare_approval(client, "approval-security")
    snapshot = client.get(f"/api/v1/tasks/{data['task_id']}", headers=AUTH_HEADERS)
    assert snapshot.status_code == 200
    assert_schema(snapshot.json(), "TaskSnapshotResponse")
    snapshot_data = snapshot.json()["data"]
    assert snapshot_data["evidence_version"] == 2
    assert snapshot_data["pending_approval"]["approval_id"] == pending["approval_id"]
    assert snapshot_data["work_order"]["status"] == "APPROVAL_PENDING"
    assert {item["event_type"] for item in snapshot_data["timeline"]} == {
        "ALARM_RAISED",
        "FIELD_MEASUREMENT_COMPLETED",
    }

    base = {
        "approval_id": pending["approval_id"],
        "approval_challenge": pending["approval_challenge"],
        "decision": "APPROVE",
        "evidence_version": pending["evidence_version"],
    }
    wrong_challenge = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "wrong-challenge"},
        json={**base, "approval_challenge": "wrong"},
    )
    stale = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "stale-evidence"},
        json={**base, "evidence_version": 999},
    )
    assert wrong_challenge.status_code == 409
    assert wrong_challenge.json()["error"]["code"] == "APPROVAL_CHALLENGE_INVALID"
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "EVIDENCE_VERSION_CONFLICT"


def test_approved_work_order_completion_closes_verified_task(client):
    data, pending = prepare_approval(client, "approval-complete")
    approval = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "approve-work-order"},
        json={
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "APPROVE",
            "evidence_version": pending["evidence_version"],
        },
    )
    assert approval.status_code == 200
    assert_schema(approval.json(), "ApprovalDecisionResponse")
    assert approval.json()["data"]["task_state"] == "MAINTENANCE_PROCESSING"
    work_order_id = approval.json()["data"]["work_order_id"]

    replay = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "approval-replay"},
        json={
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "APPROVE",
            "evidence_version": pending["evidence_version"],
        },
    )
    assert replay.status_code == 409

    completed = client.post(
        "/api/v1/events",
        headers=AUTH_HEADERS,
        json=work_event(data, work_order_id, "evt-work-complete", True),
    )
    duplicate = client.post(
        "/api/v1/events",
        headers=AUTH_HEADERS,
        json=work_event(data, work_order_id, "evt-work-complete", True),
    )
    assert completed.json()["data"]["task_state"] == "CLOSED"
    assert duplicate.json()["data"]["duplicate"] is True

    snapshot = client.get(f"/api/v1/tasks/{data['task_id']}", headers=AUTH_HEADERS)
    body = snapshot.json()["data"]
    assert body["evidence_version"] == 3
    assert body["work_order"]["status"] == "COMPLETED"
    assert body["maintenance_validation"]["status"] == "VERIFIED"
    assert body["maintenance_validation"]["sample_status"] == "APPROVED"
    assert body["conflicts"] == []


def test_unimproved_completion_remains_in_validation_with_conflict(client):
    data, pending = prepare_approval(client, "approval-conflict")
    approval = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "approve-conflict"},
        json={
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "APPROVE",
            "evidence_version": pending["evidence_version"],
        },
    )
    work_order_id = approval.json()["data"]["work_order_id"]
    completed = client.post(
        "/api/v1/events",
        headers=AUTH_HEADERS,
        json=work_event(data, work_order_id, "evt-work-conflict", False),
    )
    assert completed.json()["data"]["task_state"] == "RESULT_VALIDATION"
    snapshot = client.get(f"/api/v1/tasks/{data['task_id']}", headers=AUTH_HEADERS)
    assert snapshot.json()["data"]["maintenance_validation"]["status"] == "CONFLICTING"
    assert len(snapshot.json()["data"]["conflicts"]) == 1


def test_rejected_approval_returns_to_human_decision(client):
    data, pending = prepare_approval(client, "approval-reject")
    rejected = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "reject-work-order"},
        json={
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "REJECT",
            "evidence_version": pending["evidence_version"],
            "comment": "需要补充检查范围",
        },
    )
    assert rejected.json()["data"]["task_state"] == "HUMAN_DECISION"
    snapshot = client.get(f"/api/v1/tasks/{data['task_id']}", headers=AUTH_HEADERS)
    assert snapshot.json()["data"]["pending_approval"] is None
    assert snapshot.json()["data"]["work_order"]["status"] == "DRAFT"


def test_expired_approval_challenge_is_rejected(client, app):
    data, pending = prepare_approval(client, "approval-expired")
    with app.state.database.session_factory.begin() as session:
        approval = session.get(ApprovalRecord, pending["approval_id"])
        approval.expires_at = "2020-01-01T00:00:00+00:00"
    response = client.post(
        f"/api/v1/tasks/{data['task_id']}/approvals",
        headers={**AUTH_HEADERS, "Idempotency-Key": "expired-approval"},
        json={
            "approval_id": pending["approval_id"],
            "approval_challenge": pending["approval_challenge"],
            "decision": "APPROVE",
            "evidence_version": pending["evidence_version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_CHALLENGE_INVALID"
