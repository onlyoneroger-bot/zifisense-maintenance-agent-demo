import hashlib
import json

import pytest
from conftest import AUTH_HEADERS, LIMITED_HEADERS

from zifisense_agent_api.config import Settings
from zifisense_agent_api.infrastructure.auth import ApiKeyAuthenticator


def _key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client_json(records: list[dict]) -> str:
    return json.dumps(records, separators=(",", ":"))


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer invalid-key"}],
)
def test_capabilities_rejects_missing_or_invalid_key(client, headers):
    response = client.get("/api/v1/capabilities", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


def test_valid_key_without_scope_returns_403(client):
    response = client.get("/api/v1/capabilities", headers=LIMITED_HEADERS)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_SCOPE"


def test_request_id_is_reflected_in_success_and_error(client):
    success = client.get(
        "/api/v1/capabilities",
        headers={**AUTH_HEADERS, "X-Request-ID": "caller-request-001"},
    )
    error = client.get(
        "/api/v1/capabilities",
        headers={"Authorization": "Bearer invalid", "X-Request-ID": "caller-request-002"},
    )
    assert success.json()["request_id"] == "caller-request-001"
    assert error.json()["request_id"] == "caller-request-002"
    assert success.json()["trace_id"].startswith("trace_")
    assert error.json()["trace_id"].startswith("trace_")


def test_request_id_accepts_128_characters_and_rejects_129(client):
    maximum = "a" * 128
    too_long = "b" * 129
    accepted = client.get(
        "/api/v1/capabilities",
        headers={**AUTH_HEADERS, "X-Request-ID": maximum},
    )
    rejected = client.get(
        "/api/v1/capabilities",
        headers={**AUTH_HEADERS, "X-Request-ID": too_long},
    )

    assert accepted.status_code == 200
    assert accepted.json()["request_id"] == maximum
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "INVALID_REQUEST"


def test_configured_api_clients_map_three_keys_to_accounts():
    records = [
        {
            "client_id": f"zifisense-user-{index}",
            "api_key_hash": _key_hash(f"user-key-{index}"),
            "scopes": ["capability:read", "mcp:use"],
        }
        for index in range(1, 4)
    ]
    settings = Settings(_env_file=None, api_clients_json=_client_json(records))
    authenticator = ApiKeyAuthenticator(settings)

    for index in range(1, 4):
        identity = authenticator.authenticate(f"user-key-{index}")
        assert identity is not None
        assert identity.client_id == f"zifisense-user-{index}"
        assert identity.scopes == frozenset({"capability:read", "mcp:use"})

    assert authenticator.authenticate("wrong-key") is None


@pytest.mark.parametrize(
    "records, expected",
    [
        (
            [
                {
                    "client_id": "duplicate-user",
                    "api_key_hash": "1" * 64,
                    "scopes": ["mcp:use"],
                },
                {
                    "client_id": "DUPLICATE-USER",
                    "api_key_hash": "2" * 64,
                    "scopes": ["mcp:use"],
                },
            ],
            "duplicate client_id",
        ),
        (
            [
                {
                    "client_id": "user-one",
                    "api_key_hash": "3" * 64,
                    "scopes": ["mcp:use"],
                },
                {
                    "client_id": "user-two",
                    "api_key_hash": "3" * 64,
                    "scopes": ["mcp:use"],
                },
            ],
            "duplicate API key hashes",
        ),
    ],
)
def test_configured_api_clients_reject_duplicates(records, expected):
    with pytest.raises(ValueError, match=expected):
        Settings(_env_file=None, api_clients_json=_client_json(records))


@pytest.mark.parametrize(
    "record",
    [
        {
            "client_id": "invalid-hash-user",
            "api_key_hash": "not-a-sha256-hash",
            "scopes": ["mcp:use"],
        },
        {
            "client_id": "empty-scope-user",
            "api_key_hash": "4" * 64,
            "scopes": [],
        },
    ],
)
def test_configured_api_clients_reject_invalid_records(record):
    with pytest.raises(ValueError, match="API_CLIENTS_JSON must be"):
        Settings(_env_file=None, api_clients_json=_client_json([record]))


def test_disabled_configured_api_client_is_not_authenticated():
    settings = Settings(
        _env_file=None,
        api_clients_json=_client_json(
            [
                {
                    "client_id": "enabled-user",
                    "api_key_hash": _key_hash("enabled-key"),
                    "scopes": ["mcp:use"],
                },
                {
                    "client_id": "disabled-user",
                    "api_key_hash": _key_hash("disabled-key"),
                    "scopes": ["mcp:use"],
                    "enabled": False,
                },
            ]
        ),
    )
    authenticator = ApiKeyAuthenticator(settings)

    assert authenticator.authenticate("enabled-key") is not None
    assert authenticator.authenticate("disabled-key") is None


def test_configured_clients_do_not_require_legacy_hashes():
    settings = Settings(
        _env_file=None,
        evaluator_api_key_hash="",
        limited_api_key_hash="",
        api_clients_json=_client_json(
            [
                {
                    "client_id": "deployment-user",
                    "api_key_hash": _key_hash("deployment-key"),
                    "scopes": ["mcp:use"],
                }
            ]
        ),
    )
    assert settings.configured_api_clients()[0].client_id == "deployment-user"


def test_missing_configured_and_legacy_clients_fails_closed():
    with pytest.raises(ValueError, match="Configure API_CLIENTS_JSON"):
        Settings(
            _env_file=None,
            evaluator_api_key_hash="",
            limited_api_key_hash="",
            api_clients_json="",
        )
