from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lists_baseline_applications() -> None:
    response = client.get("/api/v1/applications")
    assert response.status_code == 200
    applications = response.json()
    assert [item["id"] for item in applications] == ["lyra-narrative", "lyra-print", "hospital-ai"]


def test_application_detail_exposes_capabilities() -> None:
    response = client.get("/api/v1/applications/lyra-narrative")
    assert response.status_code == 200
    payload = response.json()
    assert "model.generate" in payload["capabilities_consumed"]
    assert payload["integration_type"] == "external"


def test_unknown_application_returns_404() -> None:
    response = client.get("/api/v1/applications/missing")
    assert response.status_code == 404


def test_invalid_manifest_returns_actionable_errors() -> None:
    response = client.post("/api/v1/applications/validate/manifest", json={"manifest": {"id": "Bad ID"}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["errors"]
