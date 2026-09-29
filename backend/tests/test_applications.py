import httpx
import pytest
from fastapi.testclient import TestClient

from app.infrastructure.platforms import PlatformSettings
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
    assert ready.json() == {"status": "ready", "registered_applications": 3, "registered_plugins": 3}


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
    assert payload["launch_mode"] == "workspace"
    assert payload["integration_type"] == "iframe"
    assert payload["url"].startswith("https://")
    assert payload["allowed_origins"] == ["https://hospital-ai.example.com"]


def test_page_configuration_controls_order_visibility_roles_and_launch_mode(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/page-config/lyra-narrative",
        json={
            "name_override": "写作中心",
            "navigation_order": 90,
            "visible_roles": ["writer"],
            "default_launch_mode": "standalone",
        },
    )
    assert response.status_code == 200
    assert response.json()["name_override"] == "写作中心"

    writer_nav = client.get("/api/v1/navigation", headers={"X-Lyra-Roles": "writer"}).json()
    reader_nav = client.get("/api/v1/navigation", headers={"X-Lyra-Roles": "reader"}).json()
    assert any(item["name"] == "写作中心" for item in writer_nav)
    assert all(item["id"] != "lyra-narrative" for item in reader_nav)
    assert writer_nav[-1]["id"] == "lyra-narrative"

    detail = client.get("/api/v1/applications/lyra-narrative").json()
    assert detail["default_launch_mode"] == "standalone"
    launch = client.post("/api/v1/applications/lyra-narrative/launch").json()
    assert launch["launch_mode"] == "standalone"
    assert launch["url"] == detail["standalone_url"]

    hidden = client.patch("/api/v1/page-config/lyra-narrative", json={"hidden": True})
    assert hidden.status_code == 200
    admin_nav = client.get("/api/v1/navigation").json()
    assert all(item["id"] != "lyra-narrative" for item in admin_nav)

    audit = client.get("/api/v1/audit/events").json()
    assert audit[0]["action"] == "page-config.updated"


def test_gateway_and_agent_os_capabilities_are_invoked_through_hub(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if host == "gateway.local" and path == "/v1/models":
            assert request.headers["X-Free-LLM-Token"] == "gateway-token"
            return httpx.Response(200, json={"data": [{"id": "auto"}]})
        if host == "gateway.local" and path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if host == "agents.local" and path == "/api/agents":
            assert request.headers["Authorization"] == "Bearer agent-token"
            return httpx.Response(200, json={"items": [{"id": "writer"}], "total": 1, "limit": 50, "offset": 0})
        if host == "agents.local" and path == "/api/runtime/execute":
            assert request.headers["Authorization"] == "Bearer runtime-token"
            return httpx.Response(200, json={"status": "succeeded", "final_response": "done"})
        return httpx.Response(404, json={"detail": "not mocked"})

    settings = PlatformSettings(
        gateway_url="https://gateway.local",
        gateway_token="gateway-token",
        agent_os_url="https://agents.local",
        agent_os_token="agent-token",
        agent_runtime_token="runtime-token",
    )
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'platform-test.db'}",
        platform_settings=settings,
        platform_transport=httpx.MockTransport(handler),
    )
    test_client = TestClient(app)

    platform = test_client.get("/api/v1/platform/status")
    assert platform.status_code == 200
    assert all(item["reachable"] for item in platform.json()["services"])

    models = test_client.post("/api/v1/capabilities/model.list/invoke", json={"payload": {}})
    agents = test_client.post("/api/v1/capabilities/agent.list/invoke", json={"payload": {}})
    generated = test_client.post(
        "/api/v1/capabilities/model.generate/invoke",
        json={"payload": {"prompt": "hello"}},
    )
    executed = test_client.post(
        "/api/v1/capabilities/agent.run/invoke",
        json={"payload": {"prompt": "do work", "agent_id": "writer"}},
    )
    assert models.json()["result"]["data"][0]["id"] == "auto"
    assert agents.json()["result"]["items"][0]["id"] == "writer"
    assert generated.json()["result"]["choices"][0]["message"]["content"] == "ok"
    assert executed.json()["result"]["status"] == "succeeded"
