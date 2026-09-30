import httpx
from fastapi.testclient import TestClient

from app.infrastructure.platforms import PlatformSettings
from app.main import create_app


def _integration_client(tmp_path) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gateway.local" and request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "integrated"}}]},
            )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "not mocked"})

    return TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'integration-test.db'}",
            platform_settings=PlatformSettings(
                gateway_url="https://gateway.local",
                gateway_token="gateway-token",
                agent_os_url="https://agents.local",
                agent_os_token="agent-token",
                agent_runtime_token="runtime-token",
            ),
            platform_transport=httpx.MockTransport(handler),
            integration_tokens={"lyra-narrative": "narrative-secret"},
        )
    )


def test_integration_contract_is_discoverable(tmp_path) -> None:
    client = _integration_client(tmp_path)

    response = client.get("/api/v1/integration")
    assert response.status_code == 200
    payload = response.json()
    assert payload["protocol_version"] == "1.0"
    assert payload["workspace_bridge_version"] == "1.0"
    assert set(payload["transports"]) == {"rest", "postmessage"}
    assert payload["endpoints"]["openapi"] == "/openapi.json"

    app_contract = client.get("/api/v1/integration/apps/lyra-narrative")
    assert app_contract.status_code == 200
    app_payload = app_contract.json()
    assert app_payload["rest"]["enabled"] is True
    assert "model.generate" in app_payload["capabilities"]["consumes"]


def test_external_app_capability_invocation_is_scoped_and_authenticated(tmp_path) -> None:
    client = _integration_client(tmp_path)
    path = "/api/v1/integration/apps/lyra-narrative/capabilities/model.generate/invoke"

    missing = client.post(path, json={"payload": {"prompt": "hello"}})
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    invalid = client.post(
        path,
        json={"payload": {"prompt": "hello"}},
        headers={"Authorization": "Bearer wrong"},
    )
    assert invalid.status_code == 401

    success = client.post(
        path,
        json={"payload": {"prompt": "hello"}},
        headers={"Authorization": "Bearer narrative-secret"},
    )
    assert success.status_code == 200
    payload = success.json()
    assert payload["app_id"] == "lyra-narrative"
    assert payload["capability"] == "model.generate"
    assert payload["source"] == "gateway"
    assert payload["result"]["choices"][0]["message"]["content"] == "integrated"

    undeclared = client.post(
        "/api/v1/integration/apps/lyra-narrative/capabilities/agent.list/invoke",
        json={"payload": {}},
        headers={"Authorization": "Bearer narrative-secret"},
    )
    assert undeclared.status_code == 403

    audit = client.get("/api/v1/audit/events").json()
    assert audit[0]["action"] == "integration.capability_invoked"
    assert audit[0]["target_id"] == "lyra-narrative"
    assert audit[0]["payload"] == {"capability": "model.generate", "source": "gateway"}


def test_external_api_is_disabled_until_app_token_is_configured(tmp_path) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'integration-disabled.db'}",
            integration_tokens={},
        )
    )
    response = client.post(
        "/api/v1/integration/apps/lyra-narrative/capabilities/model.generate/invoke",
        json={"payload": {"prompt": "hello"}},
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 503



def test_openapi_exposes_bearer_security_for_external_integrations(tmp_path) -> None:
    client = _integration_client(tmp_path)
    schema = client.get("/openapi.json").json()

    security_schemes = schema["components"]["securitySchemes"]
    assert "HTTPBearer" in security_schemes
    assert security_schemes["HTTPBearer"]["scheme"] == "bearer"

    operation = schema["paths"][
        "/api/v1/integration/apps/{app_id}/capabilities/{capability}/invoke"
    ]["post"]
    assert {"HTTPBearer": []} in operation["security"]
