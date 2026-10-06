from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.infrastructure.agent_proxy import AgentProxyLimits, AgentsProxy
from app.infrastructure.platforms import PlatformSettings
from app.main import create_app


class AsyncHandlerTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self.handler(request)
        if asyncio.iscoroutine(result):
            result = await result
        if result.is_stream_consumed:
            result = httpx.Response(
                result.status_code,
                headers=result.headers,
                stream=MemoryResponseStream(result.content),
            )
        return result

    async def aclose(self) -> None:
        return None


class MemoryResponseStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    async def __aiter__(self):
        yield self.content

    async def aclose(self) -> None:
        return None


class TrackedStallStream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        await asyncio.sleep(60)
        yield b"{}"

    async def aclose(self) -> None:
        self.closed = True


def make_client(tmp_path, handler, *, agent_token="agents-platform-secret", timeout=5.0):
    transport = AsyncHandlerTransport(handler)
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'proxy.db'}",
        platform_settings=PlatformSettings(
            agent_os_url="https://agents.internal",
            agent_os_token=agent_token,
        ),
        agent_proxy_transport=transport,
        agent_proxy_timeout_seconds=timeout,
    )
    return TestClient(app), transport


def test_auth_and_tenant_self_routes_forward_bearer_to_fixed_agents_origin(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "agents.internal"
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "new-user-token"})
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": "user-1", "tenant_id": "tenant-a"})
        if request.url.path == "/api/v1/tenants/me/gateway":
            return httpx.Response(200, json={"configured": True})
        return httpx.Response(404, json={"detail": "not found"})

    client, transport = make_client(tmp_path, handler)
    login = client.post("/api/v1/agents/auth/login", json={"email": "a@example.test", "password": "secret"})
    assert login.status_code == 200
    assert login.json()["access_token"] == "new-user-token"

    user_headers = {"Authorization": "Bearer exact-user-token"}
    identity = client.get("/api/v1/agents/auth/me", headers=user_headers)
    gateway = client.get("/api/v1/agents/tenants/me/gateway", headers=user_headers)
    assert identity.status_code == gateway.status_code == 200
    assert [request.url.path for request in transport.requests] == [
        "/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/tenants/me/gateway"
    ]
    assert transport.requests[1].headers["authorization"] == "Bearer exact-user-token"
    assert transport.requests[2].headers["authorization"] == "Bearer exact-user-token"
    assert "x-tenant-id" not in transport.requests[1].headers
    assert "new-user-token" not in caplog.text
    assert "exact-user-token" not in caplog.text
    assert "secret" not in caplog.text


def test_governance_role_creation_is_forwarded_only_with_user_auth(tmp_path):
    role_payload = {
        "id": "novel-writer",
        "name": "小说创作助手",
        "owner": "tenant-a",
        "description": "根据大纲撰写小说章节",
    }
    client, transport = make_client(
        tmp_path,
        lambda request: httpx.Response(201, json={"id": "novel-writer", "lifecycle": "active"}),
    )

    denied = client.post("/api/v1/agents/roles", json=role_payload)
    assert denied.status_code == 401
    assert transport.requests == []

    created = client.post(
        "/api/v1/agents/roles",
        headers={"Authorization": "Bearer tenant-user-token", "X-Tenant-ID": "tenant-a"},
        json=role_payload,
    )

    assert created.status_code == 201
    assert created.json()["id"] == "novel-writer"
    assert len(transport.requests) == 1
    assert transport.requests[0].url.path == "/api/roles"
    assert transport.requests[0].headers["authorization"] == "Bearer tenant-user-token"
    assert "x-tenant-id" not in transport.requests[0].headers
    assert json.loads(transport.requests[0].read()) == role_payload


def test_role_version_publication_uses_user_auth_and_fixed_resource_path(tmp_path):
    version_payload = {
        "version": "1",
        "responsibilities": ["根据设定撰写小说章节"],
        "constraints": ["保持人物设定一致"],
    }
    client, transport = make_client(
        tmp_path,
        lambda request: httpx.Response(201, json={"role_id": "novel-writer", "version": "1"}),
    )
    response = client.post(
        "/api/v1/agents/roles/novel-writer/versions",
        headers={"Authorization": "Bearer tenant-user-token"},
        json=version_payload,
    )

    assert response.status_code == 201
    assert transport.requests[0].url.path == "/api/roles/novel-writer/versions"
    assert transport.requests[0].headers["authorization"] == "Bearer tenant-user-token"
    assert json.loads(transport.requests[0].read()) == version_payload


def test_role_list_is_paged_and_requires_user_auth(tmp_path):
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={"items": []}))
    response = client.get(
        "/api/v1/agents/roles?limit=20&offset=40&owner=ignored",
        headers={"Authorization": "Bearer tenant-user-token"},
    )
    assert response.status_code == 200
    assert transport.requests[0].url.path == "/api/roles"
    assert transport.requests[0].url.query == b"limit=20&offset=40"
    assert transport.requests[0].headers["authorization"] == "Bearer tenant-user-token"


def test_agent_run_forwards_idempotency_key_with_authenticated_tenant_user(tmp_path):
    run_payload = {"input": "写一段悬疑小说开篇"}
    client, transport = make_client(
        tmp_path,
        lambda request: httpx.Response(201, json={"data": {"run_id": "run-1", "status": "succeeded"}}),
    )
    response = client.post(
        "/api/v1/agents/agents/novel-writer/runs",
        headers={"Authorization": "Bearer tenant-user-token", "Idempotency-Key": "run-once-1"},
        json=run_payload,
    )

    assert response.status_code == 201
    assert transport.requests[0].url.path == "/api/v1/agents/novel-writer/runs"
    assert transport.requests[0].headers["authorization"] == "Bearer tenant-user-token"
    assert transport.requests[0].headers["idempotency-key"] == "run-once-1"
    assert json.loads(transport.requests[0].read()) == run_payload


def test_agent_registration_and_version_publication_keep_exact_tenant_user_scope(tmp_path):
    client, transport = make_client(tmp_path, lambda request: httpx.Response(201 if request.method == "POST" else 200, json={"id": "novel-writer-agent"}))
    headers = {"Authorization": "Bearer tenant-user-token"}
    created = client.post(
        "/api/v1/agents/agents",
        headers=headers,
        json={"id": "novel-writer-agent", "name": "Novel Writer", "owner": "user-1"},
    )
    version = client.post(
        "/api/v1/agents/agents/novel-writer-agent/versions",
        headers=headers,
        json={"version": "1", "role_id": "novel-writer", "created_by": "user-1"},
    )
    published = client.put(
        "/api/v1/agents/agents/novel-writer-agent/current-version",
        headers=headers,
        json={"version": "1"},
    )

    assert [created.status_code, version.status_code, published.status_code] == [201, 201, 200]
    assert [request.url.path for request in transport.requests] == [
        "/api/agents",
        "/api/agents/novel-writer-agent/versions",
        "/api/agents/novel-writer-agent/current-version",
    ]
    assert all(request.headers["authorization"] == "Bearer tenant-user-token" for request in transport.requests)


def test_agent_run_requires_idempotency_key_before_forwarding(tmp_path):
    client, transport = make_client(tmp_path, lambda _: httpx.Response(201, json={"data": {}}))
    response = client.post(
        "/api/v1/agents/agents/novel-writer-agent/runs",
        headers={"Authorization": "Bearer tenant-user-token"},
        json={"input": "write"},
    )
    assert response.status_code == 422
    assert transport.requests == []


def test_only_platform_admin_can_use_server_side_agents_platform_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": []})

    client, _ = make_client(tmp_path, handler)
    denied = client.get("/api/v1/agents/platform/tenants")
    assert denied.status_code == 403
    assert seen == []

    allowed = client.get(
        "/api/v1/agents/platform/tenants",
        headers={"X-Lyra-Admin-Token": "hub-admin-secret", "X-Tenant-ID": "attacker-selected"},
    )
    assert allowed.status_code == 200
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer agents-platform-secret"
    assert "x-tenant-id" not in seen[0].headers
    assert "hub-admin-secret" not in seen[0].headers.get("authorization", "")


def test_platform_tenant_pagination_is_bounded_and_only_allowed_query_values_forward(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={"items": []}))
    headers = {"X-Lyra-Admin-Token": "hub-admin-secret"}
    response = client.get(
        "/api/v1/agents/platform/tenants?limit=25&offset=50&tenant_id=ignored",
        headers=headers,
    )
    assert response.status_code == 200
    assert transport.requests[0].url.query == b"limit=25&offset=50"

    before_invalid = len(transport.requests)
    invalid = client.get("/api/v1/agents/platform/tenants?limit=201", headers=headers)
    assert invalid.status_code == 422
    assert len(transport.requests) == before_invalid


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/agents/agent-a/runs"),
        ("GET", "/api/v1/agents/auth/unknown"),
        ("DELETE", "/api/v1/agents/platform/tenants/tenant-a"),
        ("POST", "/api/v1/agents/platform/tenants/tenant-a/runs"),
        ("GET", "/api/v1/agents/tenants/me/api-credentials/../../platform/tenants"),
    ],
)
def test_unknown_or_execution_routes_are_not_proxied(tmp_path, monkeypatch, method, path):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={}))
    response = client.request(
        method,
        path,
        headers={"Authorization": "Bearer user-token", "X-Lyra-Admin-Token": "hub-admin-secret"},
    )
    assert response.status_code in {404, 405}
    assert transport.requests == []


def test_missing_platform_agents_credential_is_unavailable_and_not_fallback_to_hub_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={}), agent_token="")
    response = client.get(
        "/api/v1/agents/platform/tenants",
        headers={"X-Lyra-Admin-Token": "hub-admin-secret"},
    )
    assert response.status_code == 503
    assert transport.requests == []
    assert "hub-admin-secret" not in response.text


def test_user_routes_require_bearer_and_drop_unapproved_headers_and_query(tmp_path):
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={}))
    missing = client.get("/api/v1/agents/auth/me")
    assert missing.status_code == 401
    assert transport.requests == []

    response = client.get(
        "/api/v1/agents/auth/me?tenant_id=tenant-b",
        headers={
            "Authorization": "Bearer user-token",
            "X-Tenant-ID": "tenant-b",
            "Cookie": "session=private",
            "X-Forwarded-Host": "attacker.invalid",
        },
    )
    assert response.status_code == 200
    outgoing = transport.requests[0]
    assert outgoing.url.query == b""
    assert outgoing.headers["authorization"] == "Bearer user-token"
    assert "x-tenant-id" not in outgoing.headers
    assert "cookie" not in outgoing.headers
    assert "x-forwarded-host" not in outgoing.headers

    selected = client.get(
        "/api/v1/agents/tenants/me/admins",
        headers={"Authorization": "Bearer platform-user-token", "X-Tenant-ID": "selected-tenant"},
    )
    assert selected.status_code == 200
    selected_request = transport.requests[1]
    assert selected_request.headers["x-tenant-id"] == "selected-tenant"


def test_read_only_proxy_route_rejects_request_body(tmp_path):
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={}))
    response = client.request(
        "GET",
        "/api/v1/agents/auth/me",
        headers={"Authorization": "Bearer user-token"},
        json={"unexpected": "body"},
    )
    assert response.status_code == 400
    assert transport.requests == []


def test_upstream_errors_are_sanitized_and_redirects_are_not_followed(tmp_path):
    client, transport = make_client(
        tmp_path,
        lambda _: httpx.Response(302, headers={"Location": "https://evil.invalid/collect"}, text="secret upstream detail"),
    )
    response = client.get("/api/v1/agents/auth/me", headers={"Authorization": "Bearer user-token"})
    assert response.status_code == 502
    assert "secret upstream detail" not in response.text
    assert len(transport.requests) == 1
    assert transport.requests[0].url.host == "agents.internal"


def test_upstream_auth_error_body_is_not_exposed(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda _: httpx.Response(401, json={"detail": "internal token lookup leaked"}),
    )
    response = client.get("/api/v1/agents/auth/me", headers={"Authorization": "Bearer user-token"})
    assert response.status_code == 401
    assert "internal token lookup leaked" not in response.text


def test_upstream_response_requires_json_and_enforces_body_limit(tmp_path):
    client, transport = make_client(
        tmp_path,
        lambda _: httpx.Response(200, content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"}),
    )
    response = client.get("/api/v1/agents/auth/me", headers={"Authorization": "Bearer user-token"})
    assert response.status_code == 502
    assert len(response.content) < 4096
    assert len(transport.requests) == 1


def test_chunked_oversized_and_compressed_upstream_responses_are_rejected(tmp_path):
    oversized = MemoryResponseStream(b"x" * (1024 * 1024 + 1))
    client, _ = make_client(
        tmp_path,
        lambda _: httpx.Response(200, headers={"content-type": "application/json"}, stream=oversized),
    )
    large = client.get("/api/v1/agents/auth/me", headers={"Authorization": "Bearer user-token"})
    assert large.status_code == 502
    assert len(large.content) < 4096

    compressed_client, _ = make_client(
        tmp_path,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": "gzip"},
            stream=MemoryResponseStream(b"compressed-secret"),
        ),
    )
    compressed = compressed_client.get(
        "/api/v1/agents/auth/me", headers={"Authorization": "Bearer user-token"}
    )
    assert compressed.status_code == 502
    assert "compressed-secret" not in compressed.text


def test_oversized_request_body_is_rejected_before_upstream_call(tmp_path):
    client, transport = make_client(tmp_path, lambda _: httpx.Response(200, json={}))
    response = client.post(
        "/api/v1/agents/auth/login",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert transport.requests == []


def test_proxy_timeout_is_absolute_and_maps_to_gateway_timeout(tmp_path):
    async def slow_handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={})

    client, transport = make_client(tmp_path, slow_handler, timeout=0.05)
    response = client.get("/api/v1/agents/auth/me", headers={"Authorization": "Bearer user-token"})
    assert response.status_code == 504
    assert transport.requests


def test_unauthenticated_slow_request_body_is_rejected_before_reading():
    async def scenario():
        body_read = False

        async def receive():
            nonlocal body_read
            body_read = True
            await asyncio.sleep(60)

        request = Request(
            {"type": "http", "method": "GET", "headers": [], "path": "/api/v1/agents/auth/me"},
            receive,
        )
        proxy = AgentsProxy(
            PlatformSettings(agent_os_url="https://agents.internal"),
            limits=AgentProxyLimits(timeout_seconds=0.02),
        )
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(
                proxy.forward(request, method="GET", agents_path="/api/v1/auth/me", auth_mode="user"),
                timeout=0.2,
            )
        assert error.value.status_code == 401
        assert not body_read

    asyncio.run(scenario())


def test_one_deadline_covers_slow_request_body_and_upstream_request():
    async def scenario():
        body_cancelled = asyncio.Event()

        async def receive():
            try:
                await asyncio.sleep(0.15)
                return {"type": "http.request", "body": b"{}", "more_body": False}
            finally:
                body_cancelled.set()

        class SlowTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                await asyncio.sleep(0.15)
                return httpx.Response(200, json={})

            async def aclose(self) -> None:
                return None

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer user-token")],
                "path": "/api/v1/agents/tenants/me/admins",
            },
            receive,
        )
        proxy = AgentsProxy(
            PlatformSettings(agent_os_url="https://agents.internal"),
            transport=SlowTransport(),
            limits=AgentProxyLimits(timeout_seconds=0.25),
        )
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(
                proxy.forward(
                    request,
                    method="POST",
                    agents_path="/api/v1/tenants/me/admins",
                    auth_mode="user",
                    json_body=True,
                ),
                timeout=0.5,
            )
        assert error.value.status_code == 504
        assert body_cancelled.is_set()

    asyncio.run(scenario())


def test_absolute_deadline_closes_stalled_upstream_response_stream():
    async def scenario():
        stream = TrackedStallStream()

        class StreamTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    stream=stream,
                )

            async def aclose(self) -> None:
                return None

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "headers": [(b"authorization", b"Bearer user-token")],
                "path": "/api/v1/agents/auth/me",
            },
            lambda: asyncio.sleep(0, result={"type": "http.request", "body": b"", "more_body": False}),
        )
        proxy = AgentsProxy(
            PlatformSettings(agent_os_url="https://agents.internal"),
            transport=StreamTransport(),
            limits=AgentProxyLimits(timeout_seconds=0.02),
        )
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(
                proxy.forward(request, method="GET", agents_path="/api/v1/auth/me", auth_mode="user"),
                timeout=0.2,
            )
        assert error.value.status_code == 504
        assert stream.closed

    asyncio.run(scenario())


def test_204_must_have_no_body_and_empty_upstream_204_is_preserved(tmp_path):
    client, _ = make_client(tmp_path, lambda _: httpx.Response(204))
    response = client.post("/api/v1/agents/auth/logout", json={"refresh_token": "refresh-token"})
    assert response.status_code == 204
    assert response.content == b""

    invalid_client, _ = make_client(
        tmp_path,
        lambda _: httpx.Response(204, content=b"not-empty", headers={"content-length": "9"}),
    )
    invalid = invalid_client.post("/api/v1/agents/auth/logout", json={"refresh_token": "refresh-token"})
    assert invalid.status_code == 502


def test_platform_connection_agents_check_only_uses_public_health(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRA_HUB_ADMIN_TOKEN", "hub-admin-secret")
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"items": [{"id": "should-not-be-read"}]})

    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'agent-health.db'}",
        platform_settings=PlatformSettings(agent_os_url="https://agents.internal", agent_os_token="probe-token"),
        platform_transport=httpx.MockTransport(handler),
    )
    client = TestClient(app)
    checked = client.post(
        "/api/v1/platform/connections/agent-os/check",
        headers={"X-Lyra-Admin-Token": "hub-admin-secret"},
        json={"base_url": "https://agents.internal", "expected_revision": 0},
    )
    assert checked.status_code == 200
    assert seen == [("GET", "/health", None)]
    assert checked.json()["probe"] == "public_health"
    assert checked.json()["credential_verified"] is False


def test_model_draft_check_and_agent_versions_are_allowlisted_routes(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tenants/me/gateway/check-draft":
            return httpx.Response(200, json={"healthy": True, "code": "gateway_reachable"})
        if request.url.path == "/api/agents/novel-agent/versions":
            return httpx.Response(200, json=[{"version": "1", "role_id": "novel-role"}])
        return httpx.Response(404)

    client, transport = make_client(tmp_path, handler)
    headers = {"Authorization": "Bearer tenant-user-token", "X-Tenant-ID": "tenant-a"}
    check = client.post(
        "/api/v1/agents/tenants/me/gateway/check-draft",
        headers=headers,
        json={"base_url": "https://gateway.example.test", "token": "draft", "model": "model-a"},
    )
    versions = client.get("/api/v1/agents/agents/novel-agent/versions", headers=headers)

    assert check.status_code == 200
    assert versions.status_code == 200
    assert [request.url.path for request in transport.requests] == [
        "/api/v1/tenants/me/gateway/check-draft", "/api/agents/novel-agent/versions"
    ]
    assert transport.requests[0].headers["authorization"] == "Bearer tenant-user-token"
    assert transport.requests[0].headers["x-tenant-id"] == "tenant-a"
