from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

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
        service_id = "gateway" if item["source"] == "gateway" else "agent-os"
        service_status = status_by_id[service_id]
        items.append({**item, "reachable": service_status.reachable})
    return {"data": items}


@router.post("/capabilities/{capability}/invoke", response_model=CapabilityInvocationResponse)
def invoke_capability(
    capability: str,
    request: CapabilityInvocationRequest,
    services: PlatformServices = Depends(get_platform_services),
) -> CapabilityInvocationResponse:
    catalog = {item["name"]: item for item in services.capabilities()}
    definition = catalog.get(capability)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown capability")
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
