from __future__ import annotations

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.infrastructure.platforms import PlatformSettings
from app.main import create_app


def test_platform_connection_is_encrypted_persistent_and_revisioned(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    monkeypatch.setenv("LYRA_HUB_SECRET_KEY", Fernet.generate_key().decode("ascii"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            if request.url.host == "broken-gateway.local":
                return httpx.Response(503, json={"detail": "offline"})
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            if request.headers.get("X-Free-LLM-Token") != "test-gateway-token":
                return httpx.Response(401, json={"detail": "unauthorized"})
            return httpx.Response(200, json={"data": [{"id": "auto"}]})
        return httpx.Response(404)

    db_url = f"sqlite:///{tmp_path / 'connections.db'}"
    settings = PlatformSettings(gateway_url="https://old-gateway.local")
    app = create_app(database_url=db_url, platform_settings=settings, platform_transport=httpx.MockTransport(handler))
    client = TestClient(app)
    headers = {"X-Lyra-Admin-Token": "hub-admin-secret"}

    initial = client.get("/api/v1/platform/connections").json()["data"][0]
    assert initial["revision"] == 0
    assert "token" not in initial

    draft = {
        "base_url": "https://new-gateway.local",
        "credential": "test-gateway-token",
        "expected_revision": 0,
    }
    checked = client.post("/api/v1/platform/connections/gateway/check", json=draft, headers=headers)
    assert checked.status_code == 200
    assert checked.json()["catalog_access"] is True
    assert checked.json()["catalog_count"] == 1

    saved = client.put("/api/v1/platform/connections/gateway", json=draft, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["connection"]["revision"] == 1
    assert saved.json()["connection"]["credential_configured"] is True
    assert "test-gateway-token" not in (tmp_path / "connections.db").read_bytes().decode("latin1")

    stale = client.put("/api/v1/platform/connections/gateway", json=draft, headers=headers)
    assert stale.status_code == 409

    restarted = create_app(
        database_url=db_url,
        platform_settings=settings,
        platform_transport=httpx.MockTransport(handler),
    )
    refreshed = TestClient(restarted).post("/api/v1/capabilities/model.list/invoke", json={"payload": {}})
    assert refreshed.status_code == 200
    assert refreshed.json()["result"]["data"][0]["id"] == "auto"

    bad_auth = client.post(
        "/api/v1/platform/connections/gateway/check",
        json={"base_url": "https://new-gateway.local", "credential": "wrong", "expected_revision": 1},
        headers=headers,
    )
    assert bad_auth.status_code == 200
    assert bad_auth.json()["error_code"] == "AUTH_FAILED"

    broken = client.put(
        "/api/v1/platform/connections/gateway",
        json={"base_url": "https://broken-gateway.local", "credential": "wrong", "expected_revision": 1},
        headers=headers,
    )
    assert broken.status_code == 200
    assert broken.json()["check"]["catalog_access"] is False
    assert broken.json()["connection"]["has_last_good"] is True
    restored = client.post(
        "/api/v1/platform/connections/gateway/restore?expected_revision=2", headers=headers
    )
    assert restored.status_code == 200
    assert restored.json()["connection"]["base_url"] == "https://new-gateway.local"
    cleared = client.delete(
        "/api/v1/platform/connections/gateway?expected_revision=3", headers=headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["connection"]["source"] == "environment"
    assert cleared.json()["connection"]["base_url"] == "https://old-gateway.local"

def test_admin_token_required_for_generation_and_agent_execution_is_not_supported(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    app = create_app(database_url=f"sqlite:///{tmp_path / 'auth.db'}")
    client = TestClient(app)

    unauthorized = client.post(
        "/api/v1/capabilities/model.generate/invoke",
        json={"payload": {"prompt": "billable"}},
    )
    assert unauthorized.status_code == 403

    unsupported = client.post(
        "/api/v1/capabilities/agent.run/invoke",
        json={"payload": {"prompt": "do work"}},
        headers={"X-Lyra-Admin-Token": "hub-admin-secret"},
    )
    assert unsupported.status_code == 501
    assert unsupported.json()["detail"]["code"] == "CAPABILITY_NOT_SUPPORTED"


def test_platform_write_fails_closed_without_admin_token(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LYRA_HUB_ADMIN_TOKEN", raising=False)
    app = create_app(database_url=f"sqlite:///{tmp_path / 'no-admin.db'}")
    response = TestClient(app).post(
        "/api/v1/platform/connections/gateway/check",
        json={"base_url": "https://gateway.example", "expected_revision": 0},
    )
    assert response.status_code == 503
