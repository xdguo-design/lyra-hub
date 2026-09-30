from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.domain.applications.registry import ManifestRegistry
from app.infrastructure.database import ApplicationStateRecord, Database, record_audit
from app.infrastructure.integration_auth import IntegrationTokenRegistry
from app.infrastructure.platforms import PlatformServices

router = APIRouter(prefix="/integration", tags=["integration"])


class ExternalCapabilityInvocationRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ExternalCapabilityInvocationResponse(BaseModel):
    app_id: str
    capability: str
    source: str
    result: dict[str, Any]


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def get_platform_services() -> PlatformServices:
    raise RuntimeError("Platform service dependency was not configured")


def get_token_registry() -> IntegrationTokenRegistry:
    raise RuntimeError("Integration token dependency was not configured")


@router.get("")
def integration_contract() -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "workspace_bridge_version": "1.0",
        "transports": ["rest", "postmessage"],
        "authentication": {
            "rest": "bearer-per-application",
            "postmessage": "parent-window-and-origin-validation",
        },
        "endpoints": {
            "application": "/api/v1/integration/apps/{app_id}",
            "invoke": "/api/v1/integration/apps/{app_id}/capabilities/{capability}/invoke",
            "openapi": "/openapi.json",
        },
    }


@router.get("/apps/{app_id}")
def application_integration_contract(
    app_id: str,
    registry: ManifestRegistry = Depends(get_registry),
    tokens: IntegrationTokenRegistry = Depends(get_token_registry),
) -> dict[str, Any]:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return {
        "app_id": application.id,
        "version": application.version,
        "workspace": {
            "integration_type": application.integration_type,
            "path": application.workspace_path,
        },
        "capabilities": {
            "consumes": application.capabilities_consumed,
            "provides": application.capabilities_provided,
        },
        "rest": {
            "enabled": tokens.is_configured(app_id),
            "authentication": "bearer",
            "invoke": f"/api/v1/integration/apps/{app_id}/capabilities/{{capability}}/invoke",
        },
    }


@router.post(
    "/apps/{app_id}/capabilities/{capability}/invoke",
    response_model=ExternalCapabilityInvocationResponse,
)
def invoke_application_capability(
    app_id: str,
    capability: str,
    request: ExternalCapabilityInvocationRequest,
    response: Response,
    authorization: str | None = Header(default=None, alias="Authorization"),
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
    services: PlatformServices = Depends(get_platform_services),
    tokens: IntegrationTokenRegistry = Depends(get_token_registry),
) -> ExternalCapabilityInvocationResponse:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    with database.session() as session:
        state_record = session.get(ApplicationStateRecord, app_id)
        if state_record is not None and not state_record.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application is disabled and cannot invoke Hub capabilities",
            )

    if capability not in application.capabilities_consumed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Capability is not declared by this application",
        )

    if not tokens.is_configured(app_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External integration token is not configured for this application",
        )
    if not tokens.verify_bearer(app_id, authorization):
        response.headers["WWW-Authenticate"] = "Bearer"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid application integration token",
            headers={"WWW-Authenticate": "Bearer"},
        )

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

    with database.session() as session:
        record_audit(
            session,
            action="integration.capability_invoked",
            target_type="application",
            target_id=app_id,
            payload={"capability": capability, "source": definition["source"]},
        )
        session.commit()

    return ExternalCapabilityInvocationResponse(
        app_id=app_id,
        capability=capability,
        source=str(definition["source"]),
        result=result,
    )
