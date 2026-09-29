import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'hub-test.db'}"
    return TestClient(create_app(database_url=database_url))


def test_health_and_ready(client: TestClient) -> None:
    health = client.get("/health")
    ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "registered_applications": 3}


def test_lists_baseline_applications(client: TestClient) -> None:
    response = client.get("/api/v1/applications")
    assert response.status_code == 200
    applications = response.json()
    assert [item["id"] for item in applications] == ["lyra-narrative", "lyra-print", "hospital-ai"]
    assert all(item["enabled"] for item in applications)


def test_application_detail_exposes_capabilities(client: TestClient) -> None:
    response = client.get("/api/v1/applications/lyra-narrative")
    assert response.status_code == 200
    payload = response.json()
    assert "model.generate" in payload["capabilities_consumed"]
    assert payload["integration_type"] == "external"


def test_unknown_application_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/applications/missing")
    assert response.status_code == 404


def test_invalid_manifest_returns_actionable_errors(client: TestClient) -> None:
    response = client.post("/api/v1/applications/validate/manifest", json={"manifest": {"id": "Bad ID"}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["errors"]


def test_disable_is_persistent_and_blocks_hub_launch(client: TestClient) -> None:
    disabled = client.patch("/api/v1/applications/lyra-narrative", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    detail = client.get("/api/v1/applications/lyra-narrative")
    assert detail.json()["enabled"] is False

    launch = client.post("/api/v1/applications/lyra-narrative/launch")
    assert launch.status_code == 409
    assert "disabled" in launch.json()["detail"].lower()


def test_enable_disable_mutation_is_audited(client: TestClient) -> None:
    client.patch("/api/v1/applications/lyra-print", json={"enabled": False})
    client.patch("/api/v1/applications/lyra-print", json={"enabled": True})

    response = client.get("/api/v1/audit/events")
    assert response.status_code == 200
    events = response.json()
    assert [event["action"] for event in events[:2]] == ["application.enabled", "application.disabled"]
    assert all(event["target_id"] == "lyra-print" for event in events[:2])


def test_enabled_application_can_launch(client: TestClient) -> None:
    response = client.post("/api/v1/applications/hospital-ai/launch")
    assert response.status_code == 200
    payload = response.json()
    assert payload["app_id"] == "hospital-ai"
    assert payload["mode"] == "external"
    assert payload["url"].startswith("https://")
