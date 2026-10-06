from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request, status

from app.infrastructure.platforms import PlatformSettings

AuthMode = Literal["public", "user", "platform"]
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


class _SharedAsyncTransport(httpx.AsyncBaseTransport):
    """Keep an injected test/application transport alive across proxy calls."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self.transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        return None


@dataclass(frozen=True)
class AgentProxyLimits:
    timeout_seconds: float = 5.0
    max_request_bytes: int = DEFAULT_MAX_BODY_BYTES
    max_response_bytes: int = DEFAULT_MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_request_bytes <= 0 or self.max_response_bytes <= 0:
            raise ValueError("Agents proxy limits must be positive")


class AgentsProxy:
    """Bounded proxy for explicitly mapped Agents API operations."""

    def __init__(
        self,
        settings: PlatformSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        limits: AgentProxyLimits | None = None,
    ) -> None:
        self.settings = settings
        self.transport = _SharedAsyncTransport(transport) if transport is not None else None
        self.limits = limits or AgentProxyLimits(timeout_seconds=settings.timeout_seconds)

    async def forward(
        self,
        request: Request,
        *,
        method: str,
        agents_path: str,
        auth_mode: AuthMode,
        json_body: bool = False,
        forward_tenant_header: bool = False,
        query_params: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ):
        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                return await self._forward_with_deadline(
                    request,
                    method=method,
                    agents_path=agents_path,
                    auth_mode=auth_mode,
                    json_body=json_body,
                    forward_tenant_header=forward_tenant_header,
                    query_params=query_params,
                    idempotency_key=idempotency_key,
                )
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail={"code": "AGENTS_TIMEOUT"}) from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail={"code": "AGENTS_TIMEOUT"}) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail={"code": "AGENTS_UNAVAILABLE"}) from exc

    async def _forward_with_deadline(
        self,
        request: Request,
        *,
        method: str,
        agents_path: str,
        auth_mode: AuthMode,
        json_body: bool,
        forward_tenant_header: bool,
        query_params: dict[str, str] | None,
        idempotency_key: str | None,
    ):
        base_url = self.settings.agent_os_url.rstrip("/")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise HTTPException(status_code=503, detail={"code": "AGENTS_ORIGIN_INVALID"})

        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if auth_mode == "user":
            authorization = request.headers.get("authorization", "")
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                raise HTTPException(status_code=401, detail={"code": "AGENTS_AUTH_REQUIRED"})
            headers["Authorization"] = authorization
        elif auth_mode == "platform":
            token = self.settings.agent_os_token
            if not token:
                raise HTTPException(status_code=503, detail={"code": "AGENTS_PLATFORM_CREDENTIAL_MISSING"})
            headers["Authorization"] = f"Bearer {token}"

        if forward_tenant_header:
            tenant_id = request.headers.get("x-tenant-id")
            if tenant_id:
                headers["X-Tenant-ID"] = tenant_id
        if idempotency_key is not None:
            if not idempotency_key.strip() or len(idempotency_key) > 200 or "\r" in idempotency_key or "\n" in idempotency_key:
                raise HTTPException(status_code=400, detail={"code": "INVALID_IDEMPOTENCY_KEY"})
            headers["Idempotency-Key"] = idempotency_key.strip()
        if query_params and set(query_params) - {"limit", "offset"}:
            raise HTTPException(status_code=400, detail={"code": "AGENTS_QUERY_NOT_ALLOWED"})

        body = await self._read_request_body(request, required_json=json_body)
        if body:
            headers["Content-Type"] = "application/json"

        url = f"{base_url}{agents_path}"
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.limits.timeout_seconds,
            follow_redirects=False,
        ) as client:
            async with client.stream(
                method, url, headers=headers, params=query_params, content=body
            ) as response:
                return await self._read_response(response)

    async def _read_request_body(self, request: Request, *, required_json: bool) -> bytes:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.limits.max_request_bytes:
                    raise HTTPException(status_code=413, detail={"code": "AGENTS_REQUEST_TOO_LARGE"})
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_CONTENT_LENGTH"}) from exc
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > self.limits.max_request_bytes:
                raise HTTPException(status_code=413, detail={"code": "AGENTS_REQUEST_TOO_LARGE"})
            if chunk:
                chunks.append(chunk)
        body = b"".join(chunks)
        if required_json and not body:
            raise HTTPException(status_code=400, detail={"code": "JSON_BODY_REQUIRED"})
        if body:
            if not required_json:
                raise HTTPException(status_code=400, detail={"code": "REQUEST_BODY_NOT_ALLOWED"})
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise HTTPException(status_code=415, detail={"code": "JSON_CONTENT_TYPE_REQUIRED"})
            try:
                json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_JSON_BODY"}) from exc
        return body

    async def _read_response(self, response: httpx.Response):
        from fastapi.responses import Response

        if 300 <= response.status_code < 400:
            raise HTTPException(status_code=502, detail={"code": "AGENTS_REDIRECT_REJECTED"})
        if not 200 <= response.status_code < 300:
            mapped_status = response.status_code if response.status_code in {400, 401, 403, 404, 409, 413, 422, 429} else 503
            raise HTTPException(
                status_code=mapped_status,
                detail={"code": "AGENTS_REQUEST_REJECTED", "upstream_status": response.status_code},
            )

        content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if content_encoding not in {"", "identity"}:
            raise HTTPException(status_code=502, detail={"code": "AGENTS_COMPRESSED_RESPONSE_REJECTED"})
        raw_length = response.headers.get("content-length")
        if raw_length:
            try:
                if int(raw_length) > self.limits.max_response_bytes:
                    raise HTTPException(status_code=502, detail={"code": "AGENTS_RESPONSE_TOO_LARGE"})
            except ValueError as exc:
                raise HTTPException(status_code=502, detail={"code": "AGENTS_INVALID_RESPONSE"}) from exc

        if response.status_code == status.HTTP_204_NO_CONTENT:
            async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                if chunk:
                    raise HTTPException(status_code=502, detail={"code": "AGENTS_INVALID_204"})
            return Response(status_code=204)

        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not (media_type == "application/json" or media_type.endswith("+json")):
            raise HTTPException(status_code=502, detail={"code": "AGENTS_INVALID_CONTENT_TYPE"})
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_raw(chunk_size=64 * 1024):
            size += len(chunk)
            if size > self.limits.max_response_bytes:
                raise HTTPException(status_code=502, detail={"code": "AGENTS_RESPONSE_TOO_LARGE"})
            chunks.append(chunk)
        body = b"".join(chunks)
        try:
            json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=502, detail={"code": "AGENTS_INVALID_RESPONSE"}) from exc
        return Response(
            content=body,
            status_code=response.status_code,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )
