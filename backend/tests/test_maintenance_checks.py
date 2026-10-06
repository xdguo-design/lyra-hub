from __future__ import annotations

import asyncio
import gzip
import httpx
import threading
import time

from app.infrastructure.platforms import MaintenanceChecks, PlatformSettings


class SlowDrip(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], delay_seconds: float) -> None:
        self.chunks = chunks
        self.delay_seconds = delay_seconds

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay_seconds)
            yield chunk

    async def aclose(self) -> None:
        return None


class AsyncBytes(httpx.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aiter__(self):
        yield self.data

    async def aclose(self) -> None:
        return None


class AsyncMockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler) -> None:
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await asyncio.to_thread(self.handler, request)
        stream = AsyncBytes(response.content) if response.is_stream_consumed else response.stream
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=stream,
            request=request,
        )

    async def aclose(self) -> None:
        return None


def test_checks_five_services_using_only_safe_get_requests() -> None:
    requests: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, dict(request.headers)))
        bodies = {
            ("hub.local", "/health"): {"status": "ok"},
            ("hub.local", "/ready"): {
                "status": "ready",
                "registered_applications": 2,
                "registered_plugins": 1,
            },
            ("gateway.local", "/health"): {"status": "ok"},
            ("gateway.local", "/v1/models"): {"data": [{"id": "auto"}]},
            ("agents.local", "/health"): {"status": "ok"},
            ("agents.local", "/api/v1/platform/tenants"): {"items": [], "total": 0},
            ("narrative.local", "/api/health"): {"ok": True, "service": "narrative-os"},
            ("print.local", "/health"): {"status": "UP"},
        }
        body = bodies.get((request.url.host, request.url.path))
        return httpx.Response(200 if body is not None else 404, json=body or {}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(
            hub_url="http://hub.local",
            gateway_url="http://gateway.local",
            gateway_token="gateway-secret",
            agent_os_url="http://agents.local",
            agent_os_token="agents-secret",
            narrative_url="http://narrative.local",
            print_url="http://print.local",
        ),
        async_transport=AsyncMockTransport(handler),
        jitter_seconds=0,
    )

    results = checks.run_all()

    assert {result.service_id for result in results} == {"hub", "gateway", "agents", "narrative", "print"}
    readiness = next(result for result in results if result.check_name == "hub.readiness")
    assert readiness.details == {
        "status": "ready",
        "registered_applications": 2,
        "registered_plugins": 1,
    }
    assert all(method == "GET" for method, _, _ in requests)
    assert not any(
        path in {"/v1/chat/completions", "/api/v1/agents/run", "/api/runtime/execute", "/api/print", "/api/lyra/capabilities/print.execute"}
        for _, path, _ in requests
    )
    assert next(result for result in results if result.check_name == "agents.directory").status == "empty_catalog"
    gateway_request = next(item for item in requests if item[1] == "/v1/models")
    assert gateway_request[2]["x-free-llm-token"] == "gateway-secret"
    agents_request = next(item for item in requests if item[1] == "/api/v1/platform/tenants")
    assert agents_request[2]["authorization"] == "Bearer agents-secret"
    assert next(result for result in results if result.check_name == "narrative.health").status == "healthy"


def test_checks_classify_unauthorized_timeout_and_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gateway.local" and request.url.path == "/v1/models":
            return httpx.Response(401, request=request)
        if request.url.host == "agents.local" and request.url.path == "/api/v1/platform/tenants":
            raise httpx.ReadTimeout("timed out", request=request)
        if request.url.host == "narrative.local":
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"status": "ok", "data": [1]}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(
            hub_url="http://hub.local",
            gateway_url="http://gateway.local",
            agent_os_url="http://agents.local",
            agent_os_token="service-token",
            narrative_url="http://narrative.local",
            print_url="http://print.local",
        ),
        async_transport=AsyncMockTransport(handler),
        jitter_seconds=0,
    )

    results = {(result.service_id, result.check_name): result for result in checks.run_all()}

    assert results[("gateway", "gateway.models")].error_code == "UNAUTHORIZED"
    assert results[("agents", "agents.directory")].error_code == "TIMEOUT"
    assert results[("narrative", "narrative.health")].error_code == "UPSTREAM_ERROR"
    assert results[("print", "print.health")].status == "healthy"


def test_health_probes_reject_redirects_and_non_object_or_invalid_health_shapes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hub.local" and request.url.path == "/health":
            return httpx.Response(200, json=[{"status": "ok"}], request=request)
        if request.url.host == "gateway.local" and request.url.path == "/health":
            return httpx.Response(302, json={"status": "ok"}, headers={"Location": "/login"}, request=request)
        return httpx.Response(200, json={"status": "ok", "data": ["item"]}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(
            hub_url="http://hub.local",
            gateway_url="http://gateway.local",
            agent_os_url="http://agents.local",
            narrative_url="http://narrative.local",
            print_url="http://print.local",
        ),
        async_transport=AsyncMockTransport(handler),
        jitter_seconds=0,
    )

    results = {(result.service_id, result.check_name): result for result in checks.run_all()}

    assert results[("hub", "hub.health")].error_code == "INVALID_RESPONSE"
    assert results[("gateway", "gateway.health")].error_code == "UPSTREAM_ERROR"
    assert results[("gateway", "gateway.health")].details == {"http_status": 302}


def test_print_falls_back_to_actuator_health_when_health_is_missing() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "print.local":
            paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(404, request=request)
        return httpx.Response(200, json={"status": "UP"}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(print_url="http://print.local"),
        async_transport=AsyncMockTransport(handler),
        jitter_seconds=0,
    )

    result = next(item for item in checks.run_all() if item.service_id == "print")

    assert result.status == "healthy"
    assert paths == ["/health", "/actuator/health"]


def test_checks_bound_parallel_probe_concurrency() -> None:
    lock = threading.Lock()
    active = 0
    max_active = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        body = {"data": ["model"]} if request.url.path in {"/v1/models", "/api/v1/platform/tenants"} else {"status": "ok"}
        return httpx.Response(200, json=body, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(
            hub_url="http://all.local",
            gateway_url="http://all.local",
            agent_os_url="http://all.local",
            narrative_url="http://all.local",
            print_url="http://all.local",
        ),
        async_transport=AsyncMockTransport(handler),
        max_concurrency=2,
        jitter_seconds=0,
    )

    checks.run_all()

    assert 1 < max_active <= 2


def test_absolute_deadline_stops_a_slow_drip_response() -> None:
    payload = b'{"status":"ok"}'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hub.local" and request.url.path == "/health":
            return httpx.Response(200, stream=SlowDrip([payload[:5], payload[5:10], payload[10:]], 0.04), request=request)
        return httpx.Response(200, json={"status": "ok", "data": ["entry"]}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(hub_url="http://hub.local"),
        async_transport=AsyncMockTransport(handler),
        timeout_seconds=0.08,
        retries=0,
        jitter_seconds=0,
    )

    started = time.monotonic()
    result = next(item for item in checks.run_all() if item.check_name == "hub.health")
    elapsed = time.monotonic() - started

    assert result.error_code == "TIMEOUT"
    assert elapsed < 0.2


def test_readiness_endpoint_is_bounded_by_the_absolute_deadline() -> None:
    payload = b'{"status":"ready"}'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hub.local" and request.url.path == "/ready":
            return httpx.Response(200, stream=SlowDrip([payload[:6], payload[6:12], payload[12:]], 0.04), request=request)
        return httpx.Response(200, json={"status": "ok", "data": ["entry"]}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(hub_url="http://hub.local"),
        async_transport=AsyncMockTransport(handler),
        timeout_seconds=0.08,
        retries=0,
        jitter_seconds=0,
    )

    started = time.monotonic()
    result = next(item for item in checks.run_all() if item.check_name == "hub.readiness")
    elapsed = time.monotonic() - started

    assert result.error_code == "TIMEOUT"
    assert elapsed < 0.2


def test_probe_budget_includes_the_final_read_timeout_allowance() -> None:
    checks = MaintenanceChecks(
        timeout_seconds=2,
        retries=1,
        max_concurrency=5,
        jitter_seconds=0,
        read_poll_seconds=0.05,
    )

    assert checks.max_run_seconds >= 2 * (2 + 0.05) * 2


def test_default_read_timeout_allows_normal_local_service_jitter() -> None:
    checks = MaintenanceChecks(timeout_seconds=5, retries=1, jitter_seconds=0)

    assert checks.read_poll_seconds == 1.0
    assert checks.max_run_seconds <= 60


def test_absolute_deadline_also_cancels_slow_response_headers() -> None:
    class SlowHeaders(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.host == "hub.local" and request.url.path == "/health":
                await asyncio.sleep(0.5)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=AsyncBytes(b'{"status":"ok"}'),
                request=request,
            )

        async def aclose(self) -> None:
            return None

    checks = MaintenanceChecks(
        settings=PlatformSettings(hub_url="http://hub.local"),
        async_transport=SlowHeaders(),
        timeout_seconds=0.1,
        retries=0,
        jitter_seconds=0,
    )

    started = time.monotonic()
    result = next(item for item in checks.run_all() if item.check_name == "hub.health")
    elapsed = time.monotonic() - started

    assert result.error_code == "TIMEOUT"
    assert elapsed < 0.2


def test_probe_rejects_compressed_content_before_decompression() -> None:
    compressed = gzip.compress(b"x" * 10000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hub.local" and request.url.path == "/health":
            return httpx.Response(
                200,
                content=compressed,
                headers={"Content-Encoding": "gzip"},
                request=request,
            )
        return httpx.Response(200, json={"status": "ok", "data": ["entry"]}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(hub_url="http://hub.local"),
        async_transport=AsyncMockTransport(handler),
        timeout_seconds=0.1,
        max_response_bytes=32,
        retries=0,
        jitter_seconds=0,
    )

    result = next(item for item in checks.run_all() if item.check_name == "hub.health")

    assert result.error_code == "UNSUPPORTED_CONTENT_ENCODING"


def test_streaming_probe_rejects_oversized_body_without_reading_all_bytes() -> None:
    bytes_yielded = 0

    class LargeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal bytes_yielded
            for _ in range(20):
                chunk = b"x" * 8
                bytes_yielded += len(chunk)
                yield chunk

        async def aclose(self) -> None:
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hub.local" and request.url.path == "/health":
            return httpx.Response(200, stream=LargeStream(), request=request)
        return httpx.Response(200, json={"status": "ok", "data": ["entry"]}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(hub_url="http://hub.local"),
        async_transport=AsyncMockTransport(handler),
        timeout_seconds=0.1,
        max_response_bytes=16,
        retries=0,
        jitter_seconds=0,
    )

    result = next(item for item in checks.run_all() if item.check_name == "hub.health")

    assert result.error_code == "RESPONSE_TOO_LARGE"
    assert bytes_yielded <= 24


def test_hub_readiness_uses_http_endpoint_and_returns_safe_counts() -> None:
    requests: list[str] = []
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"status": "ready", "registered_plugins": 1}, request=request)

    checks = MaintenanceChecks(
        settings=PlatformSettings(hub_url="http://hub.local"),
        async_transport=AsyncMockTransport(handler),
        jitter_seconds=0,
    )

    results = [result for result in checks.run_all() if result.service_id == "hub"]

    assert {result.check_name for result in results} == {"hub.health", "hub.readiness"}
    assert "/ready" in requests
    assert next(result for result in results if result.check_name == "hub.readiness").details == {
        "status": "ready",
        "registered_plugins": 1,
    }
