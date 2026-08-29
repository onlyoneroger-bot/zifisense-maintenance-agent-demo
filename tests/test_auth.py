import pytest
from conftest import AUTH_HEADERS, LIMITED_HEADERS


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
