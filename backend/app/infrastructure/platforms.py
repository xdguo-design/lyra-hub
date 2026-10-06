from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class PlatformSettings:
    hub_url: str = "http://127.0.0.1:8000"
    gateway_url: str = "http://127.0.0.1:8765"
    gateway_token: str = ""
    agent_os_url: str = "http://127.0.0.1:8770"
    agent_os_token: str = ""
    agent_runtime_token: str = ""
    print_url: str = "http://127.0.0.1:8080"
    narrative_url: str = "http://127.0.0.1:8001"
    print_api_key: str = ""
    shared_files_root: str = ""
    shared_file_max_bytes: int = 1048576
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> PlatformSettings:
        return cls(
            hub_url=os.getenv("LYRA_HUB_URL", cls.hub_url).rstrip("/"),
            gateway_url=os.getenv("LYRA_GATEWAY_URL", cls.gateway_url).rstrip("/"),
            gateway_token=os.getenv("LYRA_GATEWAY_TOKEN", ""),
            agent_os_url=os.getenv("LYRA_AGENT_OS_URL", cls.agent_os_url).rstrip("/"),
            agent_os_token=os.getenv("LYRA_AGENT_OS_TOKEN", ""),
            agent_runtime_token=os.getenv("LYRA_AGENT_RUNTIME_TOKEN", ""),
            print_url=os.getenv("LYRA_PRINT_URL", cls.print_url).rstrip("/"),
            narrative_url=os.getenv("LYRA_NARRATIVE_URL", cls.narrative_url).rstrip("/"),
            print_api_key=os.getenv("LYRA_PRINT_API_KEY", ""),
            shared_files_root=os.getenv("LYRA_SHARED_FILES_ROOT", ""),
            shared_file_max_bytes=int(
                os.getenv("LYRA_SHARED_FILE_MAX_BYTES", str(cls.shared_file_max_bytes))
            ),
            timeout_seconds=float(os.getenv("LYRA_PLATFORM_TIMEOUT_SECONDS", "5")),
        )


@dataclass(frozen=True)
class ServiceStatus:
    id: str
    name: str
    base_url: str
    reachable: bool
    detail: str | dict[str, Any]


@dataclass(frozen=True)
class MaintenanceCheckResult:
    service_id: str
    check_name: str
    status: str
    error_code: str | None = None
    details: dict[str, Any] | None = None
    duration_ms: int = 0


class _SharedAsyncTransport(httpx.AsyncBaseTransport):
    """Reuse an injected async transport without closing it per request."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self.transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        return None


class MaintenanceChecks:
    """Read-only health and catalog probes for the five Lyra platform services."""

    def __init__(
        self,
        settings: PlatformSettings | None = None,
        *,
        async_transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
        max_concurrency: int = 2,
        jitter_seconds: float = 0.25,
        retries: int = 1,
        max_response_bytes: int = 262144,
        read_poll_seconds: float = 1.0,
    ) -> None:
        self.settings = settings or PlatformSettings.from_env()
        self.async_transport = (
            _SharedAsyncTransport(async_transport) if async_transport is not None else None
        )
        self.timeout_seconds = min(max(timeout_seconds, 0.1), 10.0)
        self.max_concurrency = min(max(max_concurrency, 1), 5)
        self.jitter_seconds = max(0.0, jitter_seconds)
        self.retries = min(max(retries, 0), 2)
        if max_response_bytes < 1 or read_poll_seconds <= 0:
            raise ValueError("max_response_bytes and read_poll_seconds must be positive")
        self.max_response_bytes = max_response_bytes
        self.read_poll_seconds = min(read_poll_seconds, self.timeout_seconds)

    @property
    def max_run_seconds(self) -> float:
        # The absolute asyncio deadline covers connect, headers and body. Count
        # Hub=2, Gateway=2, Agents=2, Narrative=1, Print=2 logical requests.
        request_count = 9
        per_request = (self.timeout_seconds + self.read_poll_seconds) * (self.retries + 1)
        retry_jitter = min(self.jitter_seconds, 0.1) * self.retries
        waves = (request_count + self.max_concurrency - 1) // self.max_concurrency
        return waves * (per_request + retry_jitter) + self.jitter_seconds

    def run_all(self) -> list[MaintenanceCheckResult]:
        return asyncio.run(self._run_all_async())

    async def _run_all_async(self) -> list[MaintenanceCheckResult]:
        probes: tuple[Callable[[], Any], ...] = (
            self._hub,
            self._gateway,
            self._agents,
            self._narrative,
            self._print,
        )
        self._request_semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_probe(probe: Callable[[], Any]) -> list[MaintenanceCheckResult]:
            name = getattr(probe, "__name__", "service")
            service_id = name.removeprefix("_")
            try:
                if self.jitter_seconds:
                    await asyncio.sleep(random.uniform(0, self.jitter_seconds))
                return await probe()
            except Exception:
                return [self._result(service_id, f"{service_id}.health", "unhealthy", "CHECK_ERROR")]

        batches = await asyncio.gather(*(run_probe(probe) for probe in probes))
        return [result for batch in batches for result in batch]

    async def _http_check(
        self,
        service_id: str,
        check_name: str,
        base_url: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        expect_catalog: bool = False,
    ) -> MaintenanceCheckResult:
        started = time.monotonic()
        last_result: MaintenanceCheckResult | None = None
        for attempt in range(self.retries + 1):
            try:
                last_result, retryable = await self._request_once(
                    service_id,
                    check_name,
                    base_url,
                    path,
                    headers=headers,
                    expect_catalog=expect_catalog,
                )
                if not retryable or attempt >= self.retries:
                    break
            except (TimeoutError, httpx.TimeoutException):
                last_result = self._result(service_id, check_name, "unhealthy", "TIMEOUT")
                retryable = True
            except httpx.HTTPError:
                last_result = self._result(service_id, check_name, "unhealthy", "UPSTREAM_ERROR")
                retryable = True
            if retryable and attempt < self.retries and self.jitter_seconds:
                await asyncio.sleep(random.uniform(0, min(self.jitter_seconds, 0.1)))
        assert last_result is not None
        return MaintenanceCheckResult(
            last_result.service_id,
            last_result.check_name,
            last_result.status,
            last_result.error_code,
            last_result.details,
            int((time.monotonic() - started) * 1000),
        )

    async def _request_once(
        self,
        service_id: str,
        check_name: str,
        base_url: str,
        path: str,
        *,
        headers: dict[str, str] | None,
        expect_catalog: bool,
    ) -> tuple[MaintenanceCheckResult, bool]:
        loop = asyncio.get_running_loop()
        timeout = httpx.Timeout(self.timeout_seconds, read=self.read_poll_seconds)
        request_headers = {"Accept-Encoding": "identity", **(headers or {})}
        async with self._request_semaphore:
            # Start deadline after the bounded concurrency queue so queuing is
            # accounted as another request wave in max_run_seconds.
            deadline = loop.time() + self.timeout_seconds
            async with asyncio.timeout_at(deadline):
                async with httpx.AsyncClient(
                    base_url=base_url.rstrip("/"),
                    timeout=timeout,
                    transport=self.async_transport,
                    follow_redirects=False,
                ) as client:
                    async with client.stream("GET", path, headers=request_headers) as response:
                        if response.status_code in {401, 403}:
                            return self._result(service_id, check_name, "unhealthy", "UNAUTHORIZED"), False
                        if not 200 <= response.status_code < 300:
                            return (
                                self._result(
                                    service_id,
                                    check_name,
                                    "unhealthy",
                                    "UPSTREAM_ERROR",
                                    {"http_status": response.status_code},
                                ),
                                response.status_code == 429 or response.status_code >= 500,
                            )

                        content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
                        if content_encoding not in {"", "identity"}:
                            return (
                                self._result(service_id, check_name, "unhealthy", "UNSUPPORTED_CONTENT_ENCODING"),
                                False,
                            )
                        content_length = response.headers.get("content-length")
                        if content_length is not None:
                            try:
                                if int(content_length) > self.max_response_bytes:
                                    return (
                                        self._result(service_id, check_name, "unhealthy", "RESPONSE_TOO_LARGE"),
                                        False,
                                    )
                            except ValueError:
                                pass

                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > self.max_response_bytes:
                                return (
                                    self._result(service_id, check_name, "unhealthy", "RESPONSE_TOO_LARGE"),
                                    False,
                                )
                            body.extend(chunk)
                        if not body:
                            return self._result(service_id, check_name, "unhealthy", "INVALID_RESPONSE"), False
                        try:
                            payload = json.loads(body)
                        except (ValueError, json.JSONDecodeError):
                            return self._result(service_id, check_name, "unhealthy", "INVALID_RESPONSE"), False

                        if not isinstance(payload, (dict, list)):
                            return self._result(service_id, check_name, "unhealthy", "INVALID_RESPONSE"), False
                        if expect_catalog:
                            entries = self._catalog_entries(payload)
                            status = "healthy" if entries else "empty_catalog"
                            return (
                                self._result(
                                    service_id,
                                    check_name,
                                    status,
                                    "EMPTY_CATALOG" if not entries else None,
                                    {"count": len(entries)},
                                ),
                                False,
                            )
                        if not isinstance(payload, dict):
                            return self._result(service_id, check_name, "unhealthy", "INVALID_RESPONSE"), False
                        status_value = payload.get("status")
                        ok_value = payload.get("ok")
                        if not isinstance(status_value, str) and not isinstance(ok_value, bool):
                            return self._result(service_id, check_name, "unhealthy", "INVALID_RESPONSE"), False
                        reachable = (
                            status_value.lower() in {"ok", "up", "healthy", "ready"}
                            if isinstance(status_value, str)
                            else ok_value is True
                        )
                        safe_details = {
                            key: value
                            for key, value in payload.items()
                            if key in {"status", "ok", "service", "version", "registered_applications", "registered_plugins"}
                            and isinstance(value, (str, int, float, bool))
                        }
                        return (
                            self._result(
                                service_id,
                                check_name,
                                "healthy" if reachable else "unhealthy",
                                None if reachable else "NOT_READY",
                                safe_details,
                            ),
                            False,
                        )

    @staticmethod
    def _catalog_entries(body: dict[str, Any] | list[Any]) -> list[Any]:
        if isinstance(body, list):
            return body
        entries = body.get("data", body.get("items", body.get("models", body.get("agents", []))))
        if isinstance(entries, dict):
            return list(entries.values())
        return entries if isinstance(entries, list) else []

    def _result(
        self,
        service_id: str,
        check_name: str,
        status: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> MaintenanceCheckResult:
        return MaintenanceCheckResult(service_id, check_name, status, error_code, details)

    async def _hub(self) -> list[MaintenanceCheckResult]:
        return await asyncio.gather(
            self._http_check("hub", "hub.health", self.settings.hub_url, "/health"),
            self._http_check("hub", "hub.readiness", self.settings.hub_url, "/ready"),
        )

    async def _gateway(self) -> list[MaintenanceCheckResult]:
        headers = {"X-Free-LLM-Token": self.settings.gateway_token} if self.settings.gateway_token else None
        return await asyncio.gather(
            self._http_check("gateway", "gateway.health", self.settings.gateway_url, "/health"),
            self._http_check(
                "gateway", "gateway.models", self.settings.gateway_url, "/v1/models", headers=headers, expect_catalog=True
            ),
        )

    async def _agents(self) -> list[MaintenanceCheckResult]:
        headers = {"Authorization": f"Bearer {self.settings.agent_os_token}"} if self.settings.agent_os_token else None
        return await asyncio.gather(
            self._http_check("agents", "agents.health", self.settings.agent_os_url, "/health"),
                self._http_check(
                "agents", "agents.directory", self.settings.agent_os_url, "/api/v1/platform/tenants", headers=headers, expect_catalog=True
            ),
        )

    async def _narrative(self) -> list[MaintenanceCheckResult]:
        return [await self._http_check("narrative", "narrative.health", self.settings.narrative_url, "/api/health")]

    async def _print(self) -> list[MaintenanceCheckResult]:
        first = await self._http_check("print", "print.health", self.settings.print_url, "/health")
        if first.error_code == "UPSTREAM_ERROR" and (first.details or {}).get("http_status") in {404, 405}:
            first = await self._http_check("print", "print.health", self.settings.print_url, "/actuator/health")
        return [first]


class GatewayAdapter:
    def __init__(self, settings: PlatformSettings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {"X-Free-LLM-Token": self.settings.gateway_token} if self.settings.gateway_token else {}

    def status(self) -> ServiceStatus:
        try:
            with httpx.Client(
                base_url=self.settings.gateway_url,
                timeout=self.settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get("/health")
                response.raise_for_status()
                body = response.json()
            return ServiceStatus("gateway", "Lyra Gateway", self.settings.gateway_url, body.get("status") == "ok", body)
        except (httpx.HTTPError, ValueError) as exc:
            return ServiceStatus("gateway", "Lyra Gateway", self.settings.gateway_url, False, str(exc))

    def list_models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models")

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        request_payload.setdefault("model", "auto")
        if "messages" not in request_payload:
            prompt = str(request_payload.pop("prompt", "")).strip()
            if not prompt:
                raise ValueError("model.generate requires 'messages' or a non-empty 'prompt'")
            request_payload["messages"] = [{"role": "user", "content": prompt}]
        request_payload.setdefault("stream", False)
        return self._request("POST", "/v1/chat/completions", json=request_payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(
            base_url=self.settings.gateway_url,
            timeout=self.settings.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.request(method, path, headers=self._headers(), **kwargs)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Gateway returned a non-object JSON response")
        return body


class AgentOSAdapter:
    def __init__(self, settings: PlatformSettings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def _headers(self, *, runtime: bool = False) -> dict[str, str]:
        token = self.settings.agent_runtime_token if runtime else self.settings.agent_os_token
        if not token and runtime:
            token = self.settings.agent_os_token
        return {"Authorization": f"Bearer {token}"} if token else {}

    def status(self) -> ServiceStatus:
        try:
            with httpx.Client(
                base_url=self.settings.agent_os_url,
                timeout=self.settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get("/health")
                response.raise_for_status()
                body = response.json()
            return ServiceStatus("agent-os", "Agent OS", self.settings.agent_os_url, body.get("status") == "ok", body)
        except (httpx.HTTPError, ValueError) as exc:
            return ServiceStatus("agent-os", "Agent OS", self.settings.agent_os_url, False, str(exc))

    def list_agents(self) -> dict[str, Any]:
        return self._request("GET", "/api/agents", headers=self._headers())

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not str(payload.get("prompt", "")).strip():
            raise ValueError("agent.run requires a non-empty 'prompt'")
        return self._request("POST", "/api/runtime/execute", headers=self._headers(runtime=True), json=payload)

    def compile_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/workflows/compile-preview", headers=self._headers(), json=payload)

    def run_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/workflows/run", headers=self._headers(), json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(
            base_url=self.settings.agent_os_url,
            timeout=self.settings.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Agent OS returned a non-object JSON response")
        return body


class PrintAdapter:
    def __init__(self, settings: PlatformSettings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {"X-Print-Api-Key": self.settings.print_api_key} if self.settings.print_api_key else {}

    def status(self) -> ServiceStatus:
        try:
            with httpx.Client(
                base_url=self.settings.print_url,
                timeout=self.settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get("/health")
                response.raise_for_status()
                body = response.json()
            reachable = str(body.get("status", "")).upper() in {"UP", "OK"}
            return ServiceStatus("lyra-print", "Lyra Print", self.settings.print_url, reachable, body)
        except (httpx.HTTPError, ValueError) as exc:
            return ServiceStatus("lyra-print", "Lyra Print", self.settings.print_url, False, str(exc))

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        idempotency_key = str(request_payload.pop("idempotencyKey", "")).strip()
        if not idempotency_key:
            raise ValueError("print.execute requires an 'idempotencyKey'")
        kind = str(request_payload.pop("kind", "template")).strip().lower()
        if kind not in {"template", "pdf", "raw"}:
            raise ValueError("print.execute kind must be one of: template, pdf, raw")
        envelope = self._request(
            "POST",
            "/api/lyra/capabilities/print.execute",
            headers={"Idempotency-Key": idempotency_key},
            json={"payload": {**request_payload, "kind": kind}},
        )
        result = envelope.get("result", envelope)
        if not isinstance(result, dict) or not isinstance(result.get("task"), dict):
            raise ValueError("Lyra Print returned an invalid capability result")
        return result

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(
            base_url=self.settings.print_url,
            timeout=self.settings.timeout_seconds,
            transport=self.transport,
        ) as client:
            headers = {**self._headers(), **kwargs.pop("headers", {})}
            response = client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Lyra Print returned a non-object JSON response")
        return body


class ApplicationProviderAdapter:
    def __init__(
        self,
        registry: Any,
        *,
        tokens: dict[str, str] | None = None,
        base_urls: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.registry = registry
        self.tokens = tokens or {}
        self.base_urls = {
            str(app_id): str(url).rstrip("/")
            for app_id, url in (base_urls or {}).items()
            if str(app_id).strip() and str(url).strip()
        }
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    @classmethod
    def tokens_from_env(cls) -> dict[str, str]:
        raw = os.getenv("LYRA_PROVIDER_TOKENS_JSON", "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LYRA_PROVIDER_TOKENS_JSON must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LYRA_PROVIDER_TOKENS_JSON must be a JSON object")
        return {
            str(app_id): str(token)
            for app_id, token in payload.items()
            if str(app_id).strip() and str(token)
        }

    @classmethod
    def base_urls_from_env(cls) -> dict[str, str]:
        raw = os.getenv("LYRA_PROVIDER_BASE_URLS_JSON", "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LYRA_PROVIDER_BASE_URLS_JSON must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LYRA_PROVIDER_BASE_URLS_JSON must be a JSON object")
        return {
            str(app_id): str(url).rstrip("/")
            for app_id, url in payload.items()
            if str(app_id).strip() and str(url).strip()
        }

    def definitions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        owners: dict[str, str] = {}
        for summary in self.registry.list():
            detail = self.registry.get(summary.id)
            if detail is None or not detail.capabilities_provided:
                continue
            service = detail.manifest.get("service") or {}
            base_url = self.base_urls.get(
                detail.id,
                str(service.get("baseUrl") or "").rstrip("/"),
            )
            capability_path = str(
                service.get("capabilityPath") or "/api/lyra/capabilities/{capability}"
            )
            if not base_url:
                continue
            for capability in detail.capabilities_provided:
                previous_owner = owners.get(capability)
                if previous_owner is not None and previous_owner != detail.id:
                    raise RuntimeError(
                        f"capability provider collision: {capability} is provided by "
                        f"{previous_owner} and {detail.id}"
                    )
                owners[capability] = detail.id
                items.append(
                    {
                        "name": capability,
                        "source": detail.id,
                        "service_id": f"app:{detail.id}",
                        "mutation": True,
                        "description": f"Provided by application {detail.name}",
                        "base_url": base_url,
                        "capability_path": capability_path,
                    }
                )
        return items

    def status(self) -> list[ServiceStatus]:
        statuses: list[ServiceStatus] = []
        for summary in self.registry.list():
            detail = self.registry.get(summary.id)
            if detail is None or not detail.capabilities_provided:
                continue
            service = detail.manifest.get("service") or {}
            base_url = self.base_urls.get(
                detail.id,
                str(service.get("baseUrl") or "").rstrip("/"),
            )
            if not base_url:
                continue
            manifest_health_url = str(detail.health_url or "").strip()
            health_url = (
                f"{base_url}/health"
                if detail.id in self.base_urls
                else manifest_health_url or f"{base_url}/health"
            )
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.get(health_url or f"{base_url}/health")
                    response.raise_for_status()
                    body = response.json()
                reachable = isinstance(body, dict)
                statuses.append(
                    ServiceStatus(
                        f"app:{detail.id}",
                        detail.name,
                        base_url,
                        reachable,
                        body if isinstance(body, dict) else {"status": "ok"},
                    )
                )
            except (httpx.HTTPError, ValueError) as exc:
                statuses.append(
                    ServiceStatus(
                        f"app:{detail.id}",
                        detail.name,
                        base_url,
                        False,
                        str(exc),
                    )
                )
        return statuses

    def invoke(self, definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        app_id = str(definition["source"])
        token = self.tokens.get(app_id, "")
        if not token:
            raise ValueError(
                f"provider token is not configured for application {app_id}"
            )
        headers = {"Authorization": f"Bearer {token}"}
        path = str(definition["capability_path"]).replace(
            "{capability}",
            str(definition["name"]),
        )
        with httpx.Client(
            base_url=str(definition["base_url"]),
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.post(path, headers=headers, json={"payload": payload})
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Application provider returned a non-object JSON response")
        result = body.get("result", body)
        if not isinstance(result, dict):
            raise ValueError("Application provider result must be an object")
        return result


class SharedFilesAdapter:
    def __init__(self, settings: PlatformSettings) -> None:
        self.settings = settings

    def _root(self) -> Path | None:
        raw = self.settings.shared_files_root.strip()
        if not raw:
            return None
        return Path(raw).expanduser().resolve()

    def status(self) -> ServiceStatus:
        root = self._root()
        if root is None:
            return ServiceStatus(
                "shared-files",
                "Lyra Shared Files",
                "",
                False,
                "LYRA_SHARED_FILES_ROOT is not configured",
            )
        if self.settings.shared_file_max_bytes <= 0:
            return ServiceStatus(
                "shared-files",
                "Lyra Shared Files",
                str(root),
                False,
                "LYRA_SHARED_FILE_MAX_BYTES must be positive",
            )
        if not root.exists() or not root.is_dir():
            return ServiceStatus(
                "shared-files",
                "Lyra Shared Files",
                str(root),
                False,
                "configured shared files root is not a directory",
            )
        return ServiceStatus(
            "shared-files",
            "Lyra Shared Files",
            str(root),
            True,
            {
                "root": str(root),
                "max_bytes": self.settings.shared_file_max_bytes,
                "mode": "utf8-text-read-only",
            },
        )

    def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            raise ValueError("file.read requires a non-empty relative 'path'")

        requested = Path(raw_path)
        if requested.is_absolute():
            raise ValueError("file.read path must be relative")
        if any(
            part in {"", ".", ".."} or part.startswith(".")
            for part in requested.parts
        ):
            raise ValueError("file.read path contains a forbidden path segment")

        root = self._root()
        if root is None:
            raise ValueError("shared files service is not configured")
        if self.settings.shared_file_max_bytes <= 0:
            raise ValueError("shared file max bytes must be positive")
        if not root.exists() or not root.is_dir():
            raise ValueError("shared files root is unavailable")

        try:
            candidate = (root / requested).resolve(strict=True)
            relative = candidate.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ValueError(
                "requested shared file was not found or escaped the shared root"
            ) from exc

        if not candidate.is_file():
            raise ValueError("requested shared path is not a file")

        size = candidate.stat().st_size
        if size > self.settings.shared_file_max_bytes:
            raise ValueError(
                f"shared file exceeds {self.settings.shared_file_max_bytes} byte limit"
            )

        data = candidate.read_bytes()
        try:
            text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as exc:
            raise ValueError("file.read supports UTF-8 text files only") from exc

        return {
            "path": relative.as_posix(),
            "content": text,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "encoding": "utf-8",
        }


class PlatformServices:
    def __init__(
        self,
        settings: PlatformSettings | None = None,
        transport: httpx.BaseTransport | None = None,
        *,
        application_registry: Any | None = None,
        provider_tokens: dict[str, str] | None = None,
        provider_base_urls: dict[str, str] | None = None,
    ) -> None:
        self.settings = settings or PlatformSettings.from_env()
        self.transport = transport
        self.application_registry = application_registry
        self.provider_tokens = provider_tokens
        self.provider_base_urls = provider_base_urls
        self._configure_adapters()

    def _configure_adapters(self) -> None:
        self.gateway = GatewayAdapter(self.settings, self.transport)
        self.agent_os = AgentOSAdapter(self.settings, self.transport)
        self.print = PrintAdapter(self.settings, self.transport)
        self.shared_files = SharedFilesAdapter(self.settings)
        self.application_providers = (
            ApplicationProviderAdapter(
                self.application_registry,
                tokens=(
                    self.provider_tokens
                    if self.provider_tokens is not None
                    else ApplicationProviderAdapter.tokens_from_env()
                ),
                base_urls=(
                    self.provider_base_urls
                    if self.provider_base_urls is not None
                    else ApplicationProviderAdapter.base_urls_from_env()
                ),
                transport=self.transport,
                timeout_seconds=self.settings.timeout_seconds,
            )
            if self.application_registry is not None
            else None
        )

    def configure(self, settings: PlatformSettings) -> None:
        self.settings = settings
        self._configure_adapters()

    def status(self) -> list[ServiceStatus]:
        statuses = [
            self.gateway.status(),
            self.agent_os.status(),
            self.print.status(),
            self.shared_files.status(),
        ]
        if self.application_providers is not None:
            statuses.extend(self.application_providers.status())
        return statuses

    def capabilities(self) -> list[dict[str, Any]]:
        platform_items = [
            {
                "name": "model.list",
                "source": "gateway",
                "service_id": "gateway",
                "mutation": False,
                "description": "List Gateway models",
            },
            {
                "name": "model.generate",
                "source": "gateway",
                "service_id": "gateway",
                "mutation": True,
                "supported": True,
                "description": "Generate through Gateway routing",
            },
            {
                "name": "agent.list",
                "source": "agent-os",
                "service_id": "agent-os",
                "mutation": False,
                "description": "List Agent OS agents",
            },
            {
                "name": "agent.run",
                "source": "agent-os",
                "service_id": "agent-os",
                "mutation": True,
                "supported": False,
                "description": "Unavailable through Hub: use the tenant-scoped Agents run API directly",
            },
            {
                "name": "workflow.compile",
                "source": "agent-os",
                "service_id": "agent-os",
                "mutation": False,
                "supported": True,
                "description": "Compile-preview an Agent OS workflow",
            },
            {
                "name": "workflow.run",
                "source": "agent-os",
                "service_id": "agent-os",
                "mutation": True,
                "supported": False,
                "description": "Unavailable: Agent OS does not publish a supported workflow execution API",
            },
            {
                "name": "print.execute",
                "source": "lyra-print",
                "service_id": "lyra-print",
                "mutation": True,
                "description": "Create and queue a Lyra Print task",
            },
            {
                "name": "file.read",
                "source": "hub",
                "service_id": "shared-files",
                "mutation": False,
                "description": "Read an explicitly shared UTF-8 text artifact",
            },
        ]
        by_name = {item["name"]: item for item in platform_items}
        if self.application_providers is not None:
            for item in self.application_providers.definitions():
                if item["name"] not in by_name:
                    by_name[item["name"]] = item
        return list(by_name.values())

    def invoke(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        native_capabilities = {
            "model.list", "model.generate", "agent.list", "agent.run",
            "workflow.compile", "workflow.run", "print.execute", "file.read",
        }
        if self.application_providers is not None and capability not in native_capabilities:
            provider_definitions = {
                item["name"]: item
                for item in self.application_providers.definitions()
            }
            definition = provider_definitions.get(capability)
            if definition is not None:
                return self.application_providers.invoke(definition, payload)
        if capability == "model.list":
            return self.gateway.list_models()
        if capability == "model.generate":
            return self.gateway.generate(payload)
        if capability == "agent.list":
            return self.agent_os.list_agents()
        if capability == "agent.run":
            return self.agent_os.run(payload)
        if capability == "workflow.compile":
            return self.agent_os.compile_workflow(payload)
        if capability == "workflow.run":
            return self.agent_os.run_workflow(payload)
        if capability == "print.execute":
            return self.print.execute(payload)
        if capability == "file.read":
            return self.shared_files.read(payload)
        raise KeyError(capability)
