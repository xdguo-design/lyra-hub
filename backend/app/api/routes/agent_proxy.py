from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.api.routes.platform_connections import get_platform_services, require_platform_admin
from app.infrastructure.agent_proxy import AgentsProxy, AuthMode
from app.infrastructure.platforms import PlatformServices

router = APIRouter(prefix="/agents", tags=["agents-proxy"])
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def get_agent_proxy(
    request: Request,
    services: PlatformServices = Depends(get_platform_services),
) -> AgentsProxy:
    return AgentsProxy(
        services.settings,
        transport=request.app.state.agent_proxy_transport,
        limits=request.app.state.agent_proxy_limits,
    )


def _identifier(value: str) -> str:
    if not _ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail={"code": "INVALID_AGENTS_ID"})
    return value


async def _forward(
    request: Request,
    proxy: AgentsProxy,
    method: str,
    path: str,
    *,
    mode: AuthMode = "user",
    json_body: bool = False,
    forward_tenant_header: bool = False,
    query_params: dict[str, str] | None = None,
    idempotency_key: str | None = None,
):
    return await proxy.forward(
        request,
        method=method,
        agents_path=path,
        auth_mode=mode,
        json_body=json_body,
        forward_tenant_header=forward_tenant_header,
        query_params=query_params,
        idempotency_key=idempotency_key,
    )


@router.post("/auth/login")
async def login(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/v1/auth/login", mode="public", json_body=True)


@router.post("/auth/refresh")
async def refresh(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/v1/auth/refresh", mode="public", json_body=True)


@router.post("/auth/logout")
async def logout(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/v1/auth/logout", mode="public", json_body=True)


@router.post("/auth/accept-invitation")
async def accept_invitation(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/v1/auth/accept-invitation", mode="public", json_body=True)


@router.get("/auth/me")
async def current_user(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "GET", "/api/v1/auth/me")


@router.get("/roles")
async def list_roles(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    proxy: AgentsProxy = Depends(get_agent_proxy),
):
    return await _forward(
        request, proxy, "GET", "/api/roles", query_params={"limit": str(limit), "offset": str(offset)}
    )


@router.post("/roles", status_code=201)
async def create_role(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/roles", json_body=True)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    role_id = _identifier(role_id)
    return await _forward(request, proxy, "GET", f"/api/roles/{role_id}")


@router.get("/roles/{role_id}/versions")
async def list_role_versions(role_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    role_id = _identifier(role_id)
    return await _forward(request, proxy, "GET", f"/api/roles/{role_id}/versions")


@router.get("/agents/{agent_id}/versions")
async def list_agent_versions(agent_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    agent_id = _identifier(agent_id)
    return await _forward(request, proxy, "GET", f"/api/agents/{agent_id}/versions")


@router.post("/roles/{role_id}/versions", status_code=201)
async def create_role_version(role_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    role_id = _identifier(role_id)
    return await _forward(
        request, proxy, "POST", f"/api/roles/{role_id}/versions", json_body=True
    )


@router.put("/roles/{role_id}/current-version")
async def publish_role_version(role_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    role_id = _identifier(role_id)
    return await _forward(
        request, proxy, "PUT", f"/api/roles/{role_id}/current-version", json_body=True
    )


@router.get("/personas")
async def list_personas(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    proxy: AgentsProxy = Depends(get_agent_proxy),
):
    return await _forward(
        request, proxy, "GET", "/api/personas", query_params={"limit": str(limit), "offset": str(offset)}
    )


@router.post("/personas", status_code=201)
async def create_persona(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/personas", json_body=True)


@router.post("/personas/{persona_id}/versions", status_code=201)
async def create_persona_version(persona_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    persona_id = _identifier(persona_id)
    return await _forward(
        request, proxy, "POST", f"/api/personas/{persona_id}/versions", json_body=True
    )


@router.put("/personas/{persona_id}/current-version")
async def publish_persona_version(persona_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    persona_id = _identifier(persona_id)
    return await _forward(
        request, proxy, "PUT", f"/api/personas/{persona_id}/current-version", json_body=True
    )


@router.get("/agents")
async def list_agents(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    proxy: AgentsProxy = Depends(get_agent_proxy),
):
    return await _forward(
        request, proxy, "GET", "/api/agents", query_params={"limit": str(limit), "offset": str(offset)}
    )


@router.post("/agents", status_code=201)
async def create_agent(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/agents", json_body=True)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    agent_id = _identifier(agent_id)
    return await _forward(request, proxy, "GET", f"/api/agents/{agent_id}")


@router.post("/agents/{agent_id}/versions", status_code=201)
async def create_agent_version(agent_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    agent_id = _identifier(agent_id)
    return await _forward(
        request, proxy, "POST", f"/api/agents/{agent_id}/versions", json_body=True
    )


@router.put("/agents/{agent_id}/current-version")
async def publish_agent_version(agent_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    agent_id = _identifier(agent_id)
    return await _forward(
        request, proxy, "PUT", f"/api/agents/{agent_id}/current-version", json_body=True
    )


@router.post("/agents/{agent_id}/runs")
async def run_agent(
    agent_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    proxy: AgentsProxy = Depends(get_agent_proxy),
):
    agent_id = _identifier(agent_id)
    return await _forward(
        request,
        proxy,
        "POST",
        f"/api/v1/agents/{agent_id}/runs",
        json_body=True,
        idempotency_key=idempotency_key,
    )


@router.get("/runs")
async def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    proxy: AgentsProxy = Depends(get_agent_proxy),
):
    return await _forward(
        request, proxy, "GET", "/api/v1/runs", query_params={"limit": str(limit), "offset": str(offset)}
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    run_id = _identifier(run_id)
    return await _forward(request, proxy, "GET", f"/api/v1/runs/{run_id}")


@router.get("/tenants/me/admins")
async def list_tenant_admins(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "GET", "/api/v1/tenants/me/admins", forward_tenant_header=True)


@router.post("/tenants/me/admins")
async def invite_tenant_admin(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(
        request, proxy, "POST", "/api/v1/tenants/me/admins", json_body=True, forward_tenant_header=True
    )


@router.delete("/tenants/me/admins/{user_id}")
async def remove_tenant_admin(user_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    user_id = _identifier(user_id)
    return await _forward(
        request, proxy, "DELETE", f"/api/v1/tenants/me/admins/{user_id}", forward_tenant_header=True
    )


@router.get("/tenants/me/api-credentials")
async def list_api_credentials(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(
        request, proxy, "GET", "/api/v1/tenants/me/api-credentials", forward_tenant_header=True
    )


@router.post("/tenants/me/api-credentials")
async def create_api_credential(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(
        request, proxy, "POST", "/api/v1/tenants/me/api-credentials", json_body=True, forward_tenant_header=True
    )


@router.delete("/tenants/me/api-credentials/{credential_id}")
async def revoke_api_credential(credential_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    credential_id = _identifier(credential_id)
    return await _forward(
        request,
        proxy,
        "DELETE",
        f"/api/v1/tenants/me/api-credentials/{credential_id}",
        forward_tenant_header=True,
    )


@router.get("/tenants/me/gateway")
async def get_gateway_connection(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "GET", "/api/v1/tenants/me/gateway", forward_tenant_header=True)


@router.put("/tenants/me/gateway")
async def save_gateway_connection(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(
        request, proxy, "PUT", "/api/v1/tenants/me/gateway", json_body=True, forward_tenant_header=True
    )


@router.post("/tenants/me/gateway/check-draft")
async def check_gateway_draft(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(
        request, proxy, "POST", "/api/v1/tenants/me/gateway/check-draft", json_body=True, forward_tenant_header=True
    )


@router.post("/tenants/me/gateway/check")
async def check_gateway_connection(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(
        request, proxy, "POST", "/api/v1/tenants/me/gateway/check", forward_tenant_header=True
    )


@router.get("/platform/tenants", dependencies=[Depends(require_platform_admin)])
async def list_platform_tenants(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    proxy: AgentsProxy = Depends(get_agent_proxy),
):
    return await _forward(
        request,
        proxy,
        "GET",
        "/api/v1/platform/tenants",
        mode="platform",
        query_params={"limit": str(limit), "offset": str(offset)},
    )


@router.post("/platform/tenants", dependencies=[Depends(require_platform_admin)])
async def create_platform_tenant(request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    return await _forward(request, proxy, "POST", "/api/v1/platform/tenants", mode="platform", json_body=True)


@router.patch("/platform/tenants/{tenant_id}", dependencies=[Depends(require_platform_admin)])
async def update_platform_tenant(tenant_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    tenant_id = _identifier(tenant_id)
    return await _forward(request, proxy, "PATCH", f"/api/v1/platform/tenants/{tenant_id}", mode="platform", json_body=True)


@router.post("/platform/tenants/{tenant_id}/admins", dependencies=[Depends(require_platform_admin)])
async def invite_platform_tenant_admin(tenant_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)):
    tenant_id = _identifier(tenant_id)
    return await _forward(
        request, proxy, "POST", f"/api/v1/platform/tenants/{tenant_id}/admins", mode="platform", json_body=True
    )


@router.delete("/platform/tenants/{tenant_id}/admins/{user_id}", dependencies=[Depends(require_platform_admin)])
async def remove_platform_tenant_admin(
    tenant_id: str, user_id: str, request: Request, proxy: AgentsProxy = Depends(get_agent_proxy)
):
    tenant_id = _identifier(tenant_id)
    user_id = _identifier(user_id)
    return await _forward(
        request, proxy, "DELETE", f"/api/v1/platform/tenants/{tenant_id}/admins/{user_id}", mode="platform"
    )
