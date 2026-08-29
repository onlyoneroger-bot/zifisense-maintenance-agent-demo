from time import perf_counter


def test_health_is_public_fast_and_minimal(client):
    started = perf_counter()
    response = client.get("/health")
    elapsed_ms = (perf_counter() - started) * 1000

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.3.0"
    assert set(response.json()) == {"status", "version", "timestamp"}
    assert elapsed_ms < 200
