from __future__ import annotations

from pathlib import Path

import yaml
from conftest import AUTH_HEADERS, LIMITED_HEADERS, create_evaluation
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPOSITORY_DIR = Path(__file__).resolve().parents[1]
OPENAPI_PATH = (
    REPOSITORY_DIR
    / "docs"
    / "specs"
    / "纵行科技_智能运维Agent_比赛Demo_API_v1.openapi.yaml"
)
OPENAPI_BASE_URI = "urn:zifisense:agent-api:openapi"


def load_spec() -> dict:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def assert_schema(body: dict, schema_name: str) -> None:
    spec = load_spec()
    registry = Registry().with_resource(
        OPENAPI_BASE_URI,
        Resource(contents=spec, specification=DRAFT202012),
    )
    schema = {"$ref": f"{OPENAPI_BASE_URI}#/components/schemas/{schema_name}"}
    validator = Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )
    validator.validate(body)


def test_authoritative_openapi_31_is_valid():
    spec = load_spec()
    assert spec["openapi"] == "3.1.0"
    validate(spec)


def test_success_responses_match_authoritative_schemas(client):
    health = client.get("/health")
    capabilities = client.get("/api/v1/capabilities", headers=AUTH_HEADERS)
    session = client.post(
        "/api/v1/evaluation/sessions",
        headers={**AUTH_HEADERS, "Idempotency-Key": "contract-session"},
        json={"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"},
    )
    data = session.json()["data"]
    agent = client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json={
            "evaluation_session_id": data["evaluation_session_id"],
            "conversation_id": data["conversation_id"],
            "task_id": data["task_id"],
            "message": "当前设备发生了什么？",
        },
    )
    client.post(
        "/api/v1/agent/invoke",
        headers=AUTH_HEADERS,
        json={
            "evaluation_session_id": data["evaluation_session_id"],
            "conversation_id": data["conversation_id"],
            "task_id": data["task_id"],
            "message": "同意补测。",
        },
    )
    event = client.post(
        "/api/v1/events",
        headers=AUTH_HEADERS,
        json={
            "event_id": "evt-contract-field",
            "event_type": "FIELD_MEASUREMENT_COMPLETED",
            "source_system": "PORTABLE_ANALYSIS_SIMULATOR",
            "occurred_at": "2026-08-29T10:30:00+08:00",
            "evaluation_session_id": data["evaluation_session_id"],
            "task_id": data["task_id"],
            "payload": {
                "asset_id": "ASSET-REDUCER-001",
                "measurement_point_id": "MP-4F040B86-X",
                "collection_quality": "PASS",
                "sound_analysis": {"status": "ABNORMAL"},
                "vibration_analysis": {"status": "ABNORMAL"},
            },
        },
    )

    expected = (
        (health, 200, "HealthResponse"),
        (capabilities, 200, "CapabilitiesResponse"),
        (session, 201, "CreateEvaluationSessionResponse"),
        (agent, 200, "AgentInvokeResponse"),
        (event, 200, "EventIngestResponse"),
    )
    for response, status_code, schema_name in expected:
        assert response.status_code == status_code
        assert response.headers["content-type"].startswith("application/json")
        assert_schema(response.json(), schema_name)


def test_error_responses_match_authoritative_schema(client, app):
    data = create_evaluation(client, "error-contract-session")
    valid_agent_payload = {
        "evaluation_session_id": data["evaluation_session_id"],
        "conversation_id": data["conversation_id"],
        "task_id": data["task_id"],
        "message": "test",
    }

    evaluation_conflict_key = "contract-conflict-key"
    first_evaluation = client.post(
        "/api/v1/evaluation/sessions",
        headers={**AUTH_HEADERS, "Idempotency-Key": evaluation_conflict_key},
        json={"scenario_id": "reducer_gear_alarm_v1", "locale": "zh-CN"},
    )
    assert first_evaluation.status_code == 201

    responses = {
        "capabilities_401": client.get("/api/v1/capabilities"),
        "capabilities_403": client.get("/api/v1/capabilities", headers=LIMITED_HEADERS),
        "evaluation_400": client.post(
            "/api/v1/evaluation/sessions",
            headers={**AUTH_HEADERS, "Idempotency-Key": "short"},
            json={"scenario_id": "reducer_gear_alarm_v1"},
        ),
        "evaluation_401": client.post(
            "/api/v1/evaluation/sessions",
            headers={"Idempotency-Key": "contract-no-auth"},
            json={"scenario_id": "reducer_gear_alarm_v1"},
        ),
        "evaluation_403": client.post(
            "/api/v1/evaluation/sessions",
            headers={**LIMITED_HEADERS, "Idempotency-Key": "contract-no-scope"},
            json={"scenario_id": "reducer_gear_alarm_v1"},
        ),
        "evaluation_409": client.post(
            "/api/v1/evaluation/sessions",
            headers={**AUTH_HEADERS, "Idempotency-Key": evaluation_conflict_key},
            json={"scenario_id": "reducer_gear_alarm_v1", "locale": "en-US"},
        ),
        "agent_400": client.post(
            "/api/v1/agent/invoke",
            headers=AUTH_HEADERS,
            json={**valid_agent_payload, "message": ""},
        ),
        "agent_401": client.post("/api/v1/agent/invoke", json=valid_agent_payload),
        "agent_403": client.post(
            "/api/v1/agent/invoke",
            headers=LIMITED_HEADERS,
            json=valid_agent_payload,
        ),
        "agent_404": client.post(
            "/api/v1/agent/invoke",
            headers=AUTH_HEADERS,
            json={**valid_agent_payload, "task_id": "missing-task"},
        ),
    }
    app.state.rate_limiter.reset()
    app.state.settings.rate_limit_agent_per_minute = 1
    first_agent = client.post(
        "/api/v1/agent/invoke", headers=AUTH_HEADERS, json=valid_agent_payload
    )
    assert first_agent.status_code == 200
    responses["agent_429"] = client.post(
        "/api/v1/agent/invoke", headers=AUTH_HEADERS, json=valid_agent_payload
    )
    expected_statuses = {
        "capabilities_401": 401,
        "capabilities_403": 403,
        "evaluation_400": 400,
        "evaluation_401": 401,
        "evaluation_403": 403,
        "evaluation_409": 409,
        "agent_400": 400,
        "agent_401": 401,
        "agent_403": 403,
        "agent_404": 404,
        "agent_429": 429,
    }
    assert {name: response.status_code for name, response in responses.items()} == (
        expected_statuses
    )
    for response in responses.values():
        assert response.headers["content-type"].startswith("application/json")
        assert_schema(response.json(), "ErrorResponse")
