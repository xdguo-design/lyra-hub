from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class PlatformSettings:
    gateway_url: str = "http://127.0.0.1:8765"
    gateway_token: str = ""
    agent_os_url: str = "http://127.0.0.1:8770"
    agent_os_token: str = ""
    agent_runtime_token: str = ""
    print_url: str = "http://127.0.0.1:8080"
    print_api_key: str = ""
    shared_files_root: str = ""
    shared_file_max_bytes: int = 1048576
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> PlatformSettings:
        return cls(
            gateway_url=os.getenv("LYRA_GATEWAY_URL", cls.gateway_url).rstrip("/"),
            gateway_token=os.getenv("LYRA_GATEWAY_TOKEN", ""),
            agent_os_url=os.getenv("LYRA_AGENT_OS_URL", cls.agent_os_url).rstrip("/"),
            agent_os_token=os.getenv("LYRA_AGENT_OS_TOKEN", ""),
            agent_runtime_token=os.getenv("LYRA_AGENT_RUNTIME_TOKEN", ""),
            print_url=os.getenv("LYRA_PRINT_URL", cls.print_url).rstrip("/"),
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
        kind = str(request_payload.pop("kind", "template")).strip().lower()
        should_queue = bool(request_payload.pop("queue", True))
        paths = {
            "template": "/api/print-tasks",
            "pdf": "/api/print-tasks/pdf",
            "raw": "/api/print-tasks/raw",
        }
        path = paths.get(kind)
        if path is None:
            raise ValueError("print.execute kind must be one of: template, pdf, raw")

        created = self._request("POST", path, json=request_payload)
        if not should_queue:
            return {"task": created, "queued": False}

        task_id = str(created.get("id", "")).strip()
        if not task_id:
            raise ValueError("Lyra Print did not return a task id")
        queued = self._request("POST", f"/api/print-tasks/{task_id}/queue")
        return {"task": created, "queued": True, "queue_result": queued}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(
            base_url=self.settings.print_url,
            timeout=self.settings.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.request(method, path, headers=self._headers(), **kwargs)
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
        headers = {"Authorization": f"Bearer {token}"} if token else {}
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
            text = data.decode("utf-8")
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
        self.gateway = GatewayAdapter(self.settings, transport)
        self.agent_os = AgentOSAdapter(self.settings, transport)
        self.print = PrintAdapter(self.settings, transport)
        self.shared_files = SharedFilesAdapter(self.settings)
        self.application_providers = (
            ApplicationProviderAdapter(
                application_registry,
                tokens=(
                    provider_tokens
                    if provider_tokens is not None
                    else ApplicationProviderAdapter.tokens_from_env()
                ),
                base_urls=(
                    provider_base_urls
                    if provider_base_urls is not None
                    else ApplicationProviderAdapter.base_urls_from_env()
                ),
                transport=transport,
                timeout_seconds=self.settings.timeout_seconds,
            )
            if application_registry is not None
            else None
        )

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
                "description": "Execute an Agent OS runtime turn",
            },
            {
                "name": "workflow.compile",
                "source": "agent-os",
                "service_id": "agent-os",
                "mutation": False,
                "description": "Compile-preview an Agent OS workflow",
            },
            {
                "name": "workflow.run",
                "source": "agent-os",
                "service_id": "agent-os",
                "mutation": True,
                "description": "Compile and execute an Agent OS workflow",
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
                by_name[item["name"]] = item
        return list(by_name.values())

    def invoke(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.application_providers is not None:
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
