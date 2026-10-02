from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.domain.applications.registry import ManifestRegistry
from app.infrastructure.database import ApplicationStateRecord, Database, record_audit
from app.infrastructure.events import EventService, event_envelope
from app.infrastructure.integration_auth import IntegrationTokenRegistry
from app.infrastructure.platforms import PlatformServices

router = APIRouter(prefix="/integration", tags=["integration"])
bearer_scheme = HTTPBearer(auto_error=False)


class ExternalCapabilityInvocationRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ExternalCapabilityInvocationResponse(BaseModel):
    app_id: str
    capability: str
    source: str
    result: dict[str, Any]


class ExternalEventPublishRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId", min_length=1, max_length=120)
    event_type: str = Field(
        alias="eventType",
        pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$",
        max_length=160,
    )
    event_version: str = Field(default="1.0", alias="eventVersion", min_length=1, max_length=32)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="occurredAt")
    tenant_id: str | None = Field(default=None, alias="tenantId", max_length=120)
    actor_id: str | None = Field(default=None, alias="actorId", max_length=120)
    subject: str | None = Field(default=None, max_length=240)
    correlation_id: str | None = Field(default=None, alias="correlationId", max_length=120)
    causation_id: str | None = Field(default=None, alias="causationId", max_length=120)
    data: dict[str, Any] = Field(default_factory=dict)


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def get_platform_services() -> PlatformServices:
    raise RuntimeError("Platform service dependency was not configured")


def get_token_registry() -> IntegrationTokenRegistry:
    raise RuntimeError("Integration token dependency was not configured")


def get_event_service() -> EventService:
    raise RuntimeError("Event service dependency was not configured")


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
            "publish_event": "/api/v1/integration/apps/{app_id}/events",
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
            "publish_event": f"/api/v1/integration/apps/{app_id}/events",
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
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
    services: PlatformServices = Depends(get_platform_services),
    tokens: IntegrationTokenRegistry = Depends(get_token_registry),
) -> ExternalCapabilityInvocationResponse:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    if not tokens.is_configured(app_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External integration token is not configured for this application",
        )
    authorization = (
        f"{credentials.scheme} {credentials.credentials}"
        if credentials is not None
        else None
    )
    if not tokens.verify_bearer(app_id, authorization):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid application integration token",
            headers={"WWW-Authenticate": "Bearer"},
        )

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



@router.post("/apps/{app_id}/events")
def publish_application_event(
    app_id: str,
    request: ExternalEventPublishRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
    tokens: IntegrationTokenRegistry = Depends(get_token_registry),
    events: EventService = Depends(get_event_service),
) -> dict[str, Any]:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    if not tokens.is_configured(app_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External integration token is not configured for this application",
        )
    authorization = (
        f"{credentials.scheme} {credentials.credentials}"
        if credentials is not None
        else None
    )
    if not tokens.verify_bearer(app_id, authorization):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid application integration token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with database.session() as session:
        state_record = session.get(ApplicationStateRecord, app_id)
        if state_record is not None and not state_record.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application is disabled and cannot publish Hub events",
            )

    result = events.publish(
        event_id=request.event_id,
        event_type=request.event_type,
        event_version=request.event_version,
        occurred_at=request.occurred_at,
        source_type="application",
        source_id=app_id,
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        subject=request.subject,
        correlation_id=request.correlation_id,
        causation_id=request.causation_id,
        data=request.data,
    )

    with database.session() as session:
        record_audit(
            session,
            action="integration.event_published",
            target_type="application",
            target_id=app_id,
            payload={
                "event_id": request.event_id,
                "event_type": request.event_type,
                "duplicate": result.duplicate,
                "delivery_count": result.delivery_count,
            },
        )
        session.commit()

    return {
        "event": event_envelope(result.event),
        "duplicate": result.duplicate,
        "delivery_count": result.delivery_count,
    }
