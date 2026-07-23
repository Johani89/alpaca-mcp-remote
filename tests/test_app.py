from starlette.testclient import TestClient

from alpaca_connector.app import app


def test_health_and_mcp_authentication():
    with TestClient(app) as client:
        health = client.get("/health")
        unauthorized = client.post("/mcp", json={})
    assert health.status_code == 503
    assert health.json()["status"] == "misconfigured"
    assert unauthorized.status_code == 401
