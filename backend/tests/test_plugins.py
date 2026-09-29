import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'hub-plugin-test.db'}"
    return TestClient(create_app(database_url=database_url))


def test_plugins_are_registered_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/plugins")
    assert response.status_code == 200
    plugins = response.json()
    assert {item["id"] for item in plugins} == {
        "narrative-reader",
        "print-ai-diagnostics",
        "document-ai-assistant",
    }
    assert all(item["enabled"] is False for item in plugins)


def test_plugin_filter_by_application(client: TestClient) -> None:
    response = client.get("/api/v1/plugins?application_id=lyra-print")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {
        "print-ai-diagnostics",
        "document-ai-assistant",
    }


def test_plugin_cannot_enable_without_required_permissions(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/plugins/narrative-reader",
        json={"enabled": True, "granted_permissions": ["narrative.read"]},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "plugin_permissions_missing"
    assert detail["permissions"] == ["narrative.write"]


def test_plugin_enablement_and_permissions_are_persistent_and_audited(client: TestClient) -> None:
    update = client.patch(
        "/api/v1/plugins/narrative-reader",
        json={
            "enabled": True,
            "granted_permissions": ["narrative.read", "narrative.write"],
        },
    )
    assert update.status_code == 200
    assert update.json()["enabled"] is True

    detail = client.get("/api/v1/plugins/narrative-reader")
    assert detail.status_code == 200
    assert detail.json()["enabled"] is True
    assert set(detail.json()["granted_permissions"]) == {
        "narrative.read",
        "narrative.write",
    }

    events = client.get("/api/v1/audit/events").json()
    assert events[0]["action"] == "plugin.enabled"
    assert events[0]["target_id"] == "narrative-reader"


def test_invalid_plugin_manifest_returns_errors(client: TestClient) -> None:
    response = client.post(
        "/api/v1/plugins/validate/manifest",
        json={"manifest": {"schemaVersion": "1.0", "id": "Bad Plugin"}},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["errors"]
