from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class PlatformSettings:
    gateway_url: str = "http://127.0.0.1:8765"
    gateway_token: str = ""
    agent_os_url: str = "http://127.0.0.1:8770"
    agent_os_token: str = ""
    agent_runtime_token: str = ""
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "PlatformSettings":
        return cls(
            gateway_url=os.getenv("LYRA_GATEWAY_URL", cls.gateway_url).rstrip("/"),
            gateway_token=os.getenv("LYRA_GATEWAY_TOKEN", ""),
            agent_os_url=os.getenv("LYRA_AGENT_OS_URL", cls.agent_os_url).rstrip("/"),
            agent_os_token=os.getenv("LYRA_AGENT_OS_TOKEN", ""),
            agent_runtime_token=os.getenv("LYRA_AGENT_RUNTIME_TOKEN", ""),
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


class PlatformServices:
    def __init__(
        self,
        settings: PlatformSettings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or PlatformSettings.from_env()
        self.gateway = GatewayAdapter(self.settings, transport)
        self.agent_os = AgentOSAdapter(self.settings, transport)

    def status(self) -> list[ServiceStatus]:
        return [self.gateway.status(), self.agent_os.status()]

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {"name": "model.list", "source": "gateway", "mutation": False, "description": "List Gateway models"},
            {"name": "model.generate", "source": "gateway", "mutation": True, "description": "Generate through Gateway routing"},
            {"name": "agent.list", "source": "agent-os", "mutation": False, "description": "List Agent OS agents"},
            {"name": "agent.run", "source": "agent-os", "mutation": True, "description": "Execute an Agent OS runtime turn"},
            {"name": "workflow.compile", "source": "agent-os", "mutation": False, "description": "Compile-preview an Agent OS workflow"},
        ]

    def invoke(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        raise KeyError(capability)
