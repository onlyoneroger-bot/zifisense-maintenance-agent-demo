from conftest import AUTH_HEADERS


def test_sprint_one_capabilities_are_honest(client):
    response = client.get("/api/v1/capabilities", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["capabilities"] == []
    assert body["data"]["supported_event_types"] == []
    assert body["data"]["scenarios"][0]["scenario_id"] == "reducer_gear_alarm_v1"
    assert body["meta"] == {
        "api_version": "v1",
        "timestamp": body["meta"]["timestamp"],
        "is_degraded": False,
    }
    boundaries = " ".join(body["data"]["safety_boundaries"])
    assert "not yet available" in boundaries
    assert "Production-control actions are not exposed" in boundaries
