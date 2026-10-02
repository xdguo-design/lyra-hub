from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AnyHttpUrl, BaseModel, Field

from app.infrastructure.admin_auth import AdminTokenAuth
from app.infrastructure.database import EventDeliveryRecord, EventSubscriptionRecord
from app.infrastructure.events import EventService, event_envelope

admin_bearer_scheme = HTTPBearer(auto_error=False)


def get_admin_auth() -> AdminTokenAuth:
    raise RuntimeError("Admin auth dependency was not configured")


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(admin_bearer_scheme),
    auth: AdminTokenAuth = Depends(get_admin_auth),
) -> None:
    if not auth.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hub admin token is not configured",
        )
    if not auth.verify(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Hub admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    prefix="/events",
    tags=["events"],
    dependencies=[Depends(require_admin)],
)

EVENT_TYPE_PATTERN = r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$"


class EventSubscriptionCreate(BaseModel):
    subscriber_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=160)
    endpoint_url: AnyHttpUrl
    secret_ref: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    max_attempts: int = Field(default=5, ge=1, le=20)


class EventSubscriptionUpdate(BaseModel):
    enabled: bool


class EventSubscriptionResponse(BaseModel):
    id: int
    subscriber_id: str
    event_type: str
    endpoint_url: str
    secret_ref: str | None
    enabled: bool
    max_attempts: int
    created_at: datetime
    updated_at: datetime


class EventDeliveryResponse(BaseModel):
    id: int
    event_id: str
    subscription_id: int
    status: str
    attempt_count: int
    last_status_code: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


def get_event_service() -> EventService:
    raise RuntimeError("Event service dependency was not configured")


def _subscription_response(record: EventSubscriptionRecord) -> EventSubscriptionResponse:
    return EventSubscriptionResponse(
        id=record.id,
        subscriber_id=record.subscriber_id,
        event_type=record.event_type,
        endpoint_url=record.endpoint_url,
        secret_ref=record.secret_ref,
        enabled=record.enabled,
        max_attempts=record.max_attempts,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _delivery_response(record: EventDeliveryRecord) -> EventDeliveryResponse:
    return EventDeliveryResponse(
        id=record.id,
        event_id=record.event_id,
        subscription_id=record.subscription_id,
        status=record.status,
        attempt_count=record.attempt_count,
        last_status_code=record.last_status_code,
        last_error=record.last_error,
        next_attempt_at=record.next_attempt_at,
        delivered_at=record.delivered_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post(
    "/subscriptions",
    response_model=EventSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    request: EventSubscriptionCreate,
    service: EventService = Depends(get_event_service),
) -> EventSubscriptionResponse:
    event_type = request.event_type.strip().lower()
    candidate = event_type[:-2] if event_type.endswith(".*") else event_type
    if event_type != "*" and re.fullmatch(EVENT_TYPE_PATTERN, candidate) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid event type pattern",
        )

    record = service.create_subscription(
        subscriber_id=request.subscriber_id.strip(),
        event_type=event_type,
        endpoint_url=str(request.endpoint_url),
        secret_ref=request.secret_ref.strip(),
        enabled=request.enabled,
        max_attempts=request.max_attempts,
    )
    return _subscription_response(record)


@router.get("/subscriptions", response_model=list[EventSubscriptionResponse])
def list_subscriptions(
    service: EventService = Depends(get_event_service),
) -> list[EventSubscriptionResponse]:
    return [_subscription_response(item) for item in service.list_subscriptions()]


@router.patch("/subscriptions/{subscription_id}", response_model=EventSubscriptionResponse)
def update_subscription(
    subscription_id: int,
    request: EventSubscriptionUpdate,
    service: EventService = Depends(get_event_service),
) -> EventSubscriptionResponse:
    try:
        record = service.set_subscription_enabled(subscription_id, request.enabled)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event subscription not found",
        ) from exc
    return _subscription_response(record)


@router.get("")
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    service: EventService = Depends(get_event_service),
) -> dict[str, list[dict[str, Any]]]:
    return {"data": [event_envelope(item) for item in service.list_events(limit=limit)]}


@router.get("/deliveries", response_model=list[EventDeliveryResponse])
def list_deliveries(
    delivery_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    service: EventService = Depends(get_event_service),
) -> list[EventDeliveryResponse]:
    return [
        _delivery_response(item)
        for item in service.list_deliveries(status=delivery_status, limit=limit)
    ]


@router.post(
    "/deliveries/{delivery_id}/attempt",
    response_model=EventDeliveryResponse,
)
def attempt_delivery(
    delivery_id: int,
    service: EventService = Depends(get_event_service),
) -> EventDeliveryResponse:
    try:
        record = service.attempt_delivery(delivery_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event delivery not found",
        ) from exc
    return _delivery_response(record)
