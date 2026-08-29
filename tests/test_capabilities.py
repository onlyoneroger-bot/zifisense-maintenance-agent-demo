from conftest import AUTH_HEADERS


def test_sprint_two_capabilities_match_registered_read_only_tools(client):
    response = client.get("/api/v1/capabilities", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    codes = {item["code"] for item in body["data"]["capabilities"]}
    assert codes == {
        "asset_catalog_query",
        "current_fault_query",
        "fault_detail_query",
        "fault_history_query",
        "monitoring_summary",
        "operating_context_query",
        "maintenance_history_query",
        "peer_comparison",
        "context_orchestration",
        "human_input_gate",
        "portable_measurement_ingest",
        "work_order_draft",
        "approval_gated_write",
        "maintenance_result_validation",
        "audit_traceability",
    }
    assert body["data"]["supported_event_types"] == [
        "ALARM_RAISED",
        "FIELD_MEASUREMENT_COMPLETED",
        "WORK_ORDER_COMPLETED",
    ]
    assert body["data"]["scenarios"][0]["scenario_id"] == "reducer_gear_alarm_v1"
    assert body["meta"] == {
        "api_version": "v1",
        "timestamp": body["meta"]["timestamp"],
        "is_degraded": False,
    }
    boundaries = " ".join(body["data"]["safety_boundaries"])
    assert "explicitly simulated Fixture data" in boundaries
    assert "no real EAM, PLC, or DCS" in boundaries
    assert "Production-control actions are not exposed" in boundaries
