from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.api.routes.platform_connections import require_platform_admin
from app.domain.applications.registry import ManifestRegistry
from app.infrastructure.platforms import PlatformServices

router = APIRouter(tags=["capabilities"])


class CapabilityInvocationRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class CapabilityInvocationResponse(BaseModel):
    capability: str
    source: str
    result: dict[str, Any]


def get_platform_services() -> PlatformServices:
    raise RuntimeError("Platform service dependency was not configured")


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


@router.get("/platform/status")
def platform_status(services: PlatformServices = Depends(get_platform_services)) -> dict[str, Any]:
    statuses = services.status()
    return {
        "services": [
            {
                "id": item.id,
                "name": item.name,
                "base_url": item.base_url,
                "reachable": item.reachable,
                "detail": item.detail,
            }
            for item in statuses
        ]
    }


@router.get("/capabilities")
def list_capabilities(services: PlatformServices = Depends(get_platform_services)) -> dict[str, Any]:
    status_by_id = {item.id: item for item in services.status()}
    items = []
    for item in services.capabilities():
        service_id = str(item["service_id"])
        service_status = status_by_id.get(service_id)
        items.append(
            {
                **item,
                "reachable": bool(service_status and service_status.reachable),
                "supported": item.get("supported", True),
                "available": bool(service_status and service_status.reachable and item.get("supported", True)),
            }
        )
    return {"data": items}


@router.post("/capabilities/{capability}/invoke", response_model=CapabilityInvocationResponse)
def invoke_capability(
    capability: str,
    request: CapabilityInvocationRequest,
    services: PlatformServices = Depends(get_platform_services),
    x_lyra_admin_token: str | None = Header(default=None),
) -> CapabilityInvocationResponse:
    catalog = {item["name"]: item for item in services.capabilities()}
    definition = catalog.get(capability)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown capability")
    if not definition.get("supported", True):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "CAPABILITY_NOT_SUPPORTED", "detail": definition["description"]},
        )
    if definition.get("mutation", False):
        require_platform_admin(x_lyra_admin_token)
    try:
        result = services.invoke(capability, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        detail = f"Upstream returned HTTP {exc.response.status_code}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Upstream platform is unreachable") from exc
    return CapabilityInvocationResponse(capability=capability, source=definition["source"], result=result)



@router.get("/capability-dependencies")
def capability_dependencies(
    services: PlatformServices = Depends(get_platform_services),
    registry: ManifestRegistry = Depends(get_registry),
) -> dict[str, Any]:
    definitions = {item["name"]: item for item in services.capabilities()}
    service_status = {
        item.id: item.reachable
        for item in services.status()
    }

    data: list[dict[str, Any]] = []
    for application in registry.list():
        detail = registry.get(application.id)
        if detail is None:
            continue
        for capability in detail.capabilities_consumed:
            definition = definitions.get(capability)
            if definition is None:
                data.append(
                    {
                        "application_id": application.id,
                        "application_name": application.name,
                        "capability": capability,
                        "source": None,
                        "status": "missing",
                    }
                )
                continue

            source = str(definition["source"])
            service_id = str(definition["service_id"])
            data.append(
                {
                    "application_id": application.id,
                    "application_name": application.name,
                    "capability": capability,
                    "source": source,
                    "status": (
                        "unsupported"
                        if not definition.get("supported", True)
                        else "available" if service_status.get(service_id, False) else "unreachable"
                    ),
                }
            )

    return {"data": data}
