from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.infrastructure.database import Database, PlatformConnectionRecord, record_audit
from app.infrastructure.platform_connections import (
    SERVICE_FIELDS,
    connection_snapshot,
    deserialize_connection,
    serialize_connection,
)
from app.infrastructure.platforms import AgentOSAdapter, GatewayAdapter, PlatformServices, PlatformSettings

router = APIRouter(prefix="/platform/connections", tags=["platform-connections"])
ServiceId = Literal["gateway", "agent-os"]
_CONNECTION_UPDATE_LOCK = RLock()


def connection_update_lock() -> RLock:
    """Serialize persisted connection revisions with their in-memory activation."""
    return _CONNECTION_UPDATE_LOCK


class ConnectionDraft(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    credential: str | None = Field(default=None, max_length=4096)
    clear_credential: bool = False
    expected_revision: int = Field(ge=0)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("base_url must be an HTTP(S) URL without embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url cannot contain a query or fragment")
        return normalized


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def get_platform_services() -> PlatformServices:
    raise RuntimeError("Platform service dependency was not configured")


def require_platform_admin(x_lyra_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("LYRA_HUB_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform administration is disabled: LYRA_HUB_ADMIN_TOKEN is not configured",
        )
    if not x_lyra_admin_token or not hmac.compare_digest(x_lyra_admin_token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform administrator token is invalid")


def _stored(database: Database, service_id: str) -> PlatformConnectionRecord | None:
    with database.session() as session:
        return session.get(PlatformConnectionRecord, service_id)


def _redacted(service_id: str, services: PlatformServices, database: Database) -> dict[str, Any]:
    record = _stored(database, service_id)
    url_field, token_field = SERVICE_FIELDS[service_id]
    base_url = getattr(services.settings, url_field)
    token = getattr(services.settings, token_field)
    return {
        **connection_snapshot(
            service_id,
            base_url,
            token,
            record.revision if record else 0,
            source="database" if record else "environment",
        ),
        "checked_at": record.checked_at.isoformat() if record and record.checked_at else None,
        "has_last_good": bool(record and record.last_good_json),
    }


def _check(service_id: str, base_url: str, token: str, services: PlatformServices) -> dict[str, Any]:
    settings = services.settings
    if service_id == "gateway":
        candidate = PlatformSettings(**{**settings.__dict__, "gateway_url": base_url, "gateway_token": token})
        adapter: Any = GatewayAdapter(candidate, services.transport)
        catalog_name = "models"
        catalog_path = "/v1/models"
    else:
        candidate = PlatformSettings(**{**settings.__dict__, "agent_os_url": base_url, "agent_os_token": token})
        adapter = AgentOSAdapter(candidate, services.transport)
        catalog_name = "agents"
        catalog_path = "/api/agents"
    checked_at = datetime.now(UTC).isoformat()
    try:
        health = adapter.status()
        if not health.reachable:
            detail = health.detail if isinstance(health.detail, dict) else "health_check_failed"
            return {"service_id": service_id, "reachable": False, "catalog_access": False,
                    "catalog_count": None, "error_code": "HEALTH_UNAVAILABLE", "detail": detail,
                    "checked_at": checked_at}
        if service_id == "agent-os":
            return {
                "service_id": service_id,
                "reachable": True,
                "catalog_access": True,
                "catalog_count": None,
                "probe": "public_health",
                "credential_verified": False,
                "error_code": None,
                "checked_at": checked_at,
            }
        catalog = adapter.list_models() if service_id == "gateway" else adapter.list_agents()
        entries = catalog.get("data", []) if service_id == "gateway" else catalog.get("items", [])
        count = len(entries) if isinstance(entries, list) else int(catalog.get("total", 0))
        return {"service_id": service_id, "reachable": True, "catalog_access": True,
                "catalog_name": catalog_name, "catalog_path": catalog_path, "catalog_count": count,
                "error_code": None, "checked_at": checked_at}
    except httpx.HTTPStatusError as exc:
        code = "AUTH_FAILED" if exc.response.status_code in {401, 403} else "CATALOG_HTTP_ERROR"
        return {"service_id": service_id, "reachable": True, "catalog_access": False,
                "catalog_count": None, "error_code": code,
                "detail": f"catalog returned HTTP {exc.response.status_code}", "checked_at": checked_at}
    except httpx.TimeoutException:
        return {"service_id": service_id, "reachable": False, "catalog_access": False,
                "catalog_count": None, "error_code": "UPSTREAM_TIMEOUT", "checked_at": checked_at}
    except httpx.HTTPError:
        return {"service_id": service_id, "reachable": False, "catalog_access": False,
                "catalog_count": None, "error_code": "UPSTREAM_UNAVAILABLE", "checked_at": checked_at}
    except (ValueError, TypeError):
        return {"service_id": service_id, "reachable": True, "catalog_access": False,
                "catalog_count": None, "error_code": "INVALID_CATALOG_RESPONSE", "checked_at": checked_at}


@router.get("")
def get_connections(
    services: PlatformServices = Depends(get_platform_services),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    return {"data": [_redacted(key, services, database) for key in SERVICE_FIELDS]}


@router.post("/{service_id}/check", dependencies=[Depends(require_platform_admin)])
def check_connection(
    service_id: ServiceId,
    draft: ConnectionDraft,
    services: PlatformServices = Depends(get_platform_services),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    _, token_field = SERVICE_FIELDS[service_id]
    current_token = getattr(services.settings, token_field)
    token = "" if draft.clear_credential else (draft.credential if draft.credential is not None else current_token)
    record = _stored(database, service_id)
    current_revision = record.revision if record else 0
    if draft.expected_revision != current_revision:
        raise HTTPException(status_code=409, detail={"code": "REVISION_CONFLICT", "current_revision": current_revision})
    result = _check(service_id, draft.base_url, token, services)
    with database.session() as session:
        record = session.get(PlatformConnectionRecord, service_id)
        if record:
            record.checked_at = datetime.now(UTC)
        session.commit()
    return result


@router.put("/{service_id}", dependencies=[Depends(require_platform_admin)])
def save_connection(
    service_id: ServiceId,
    draft: ConnectionDraft,
    services: PlatformServices = Depends(get_platform_services),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    url_field, token_field = SERVICE_FIELDS[service_id]
    current_token = getattr(services.settings, token_field)
    token = "" if draft.clear_credential else (draft.credential if draft.credential is not None else current_token)
    checked = _check(service_id, draft.base_url, token, services)
    with connection_update_lock():
        with database.session() as session:
            record = session.get(PlatformConnectionRecord, service_id)
            revision = record.revision if record else 0
            if draft.expected_revision != revision:
                raise HTTPException(
                    status_code=409, detail={"code": "REVISION_CONFLICT", "current_revision": revision}
                )
            serialized = serialize_connection(service_id, draft.base_url, token)
            if record is None:
                record = PlatformConnectionRecord(service_id=service_id, current_json=serialized, revision=1)
                session.add(record)
            else:
                record.current_json = serialized
                record.revision += 1
            record.checked_at = datetime.now(UTC)
            if checked["reachable"] and checked["catalog_access"]:
                record.last_good_json = serialized
            record_audit(session, action="platform.connection_saved", target_type="platform", target_id=service_id,
                         payload={"revision": record.revision, "checked": checked["catalog_access"]})
            session.commit()
            revision = record.revision
        changes = {url_field: draft.base_url, token_field: token}
        services.configure(services.settings.__class__(**{**services.settings.__dict__, **changes}))
    return {"connection": _redacted(service_id, services, database), "check": checked}


@router.post("/{service_id}/restore", dependencies=[Depends(require_platform_admin)])
def restore_connection(
    service_id: ServiceId,
    expected_revision: int,
    services: PlatformServices = Depends(get_platform_services),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    with connection_update_lock():
        with database.session() as session:
            record = session.get(PlatformConnectionRecord, service_id)
            if record is None or not record.last_good_json:
                raise HTTPException(status_code=409, detail={"code": "NO_LAST_GOOD_CONNECTION"})
            if record.revision != expected_revision:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "REVISION_CONFLICT", "current_revision": record.revision},
                )
            url, token = deserialize_connection(record.last_good_json)
            record.current_json = record.last_good_json
            record.revision += 1
            record.checked_at = datetime.now(UTC)
            record_audit(session, action="platform.connection_restored", target_type="platform", target_id=service_id,
                         payload={"revision": record.revision})
            session.commit()
            revision = record.revision
        url_field, token_field = SERVICE_FIELDS[service_id]
        services.configure(services.settings.__class__(
            **{**services.settings.__dict__, url_field: url, token_field: token}
        ))
    return {"connection": _redacted(service_id, services, database), "revision": revision}


@router.delete("/{service_id}", dependencies=[Depends(require_platform_admin)])
def clear_saved_connection(
    service_id: ServiceId,
    expected_revision: int,
    services: PlatformServices = Depends(get_platform_services),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    with connection_update_lock():
        with database.session() as session:
            record = session.get(PlatformConnectionRecord, service_id)
            current_revision = record.revision if record else 0
            if expected_revision != current_revision:
                raise HTTPException(
                    status_code=409, detail={"code": "REVISION_CONFLICT", "current_revision": current_revision}
                )
            if record:
                session.delete(record)
                record_audit(session, action="platform.connection_cleared", target_type="platform", target_id=service_id,
                             payload={"revision": current_revision})
            session.commit()
        environment_settings = getattr(services, "environment_settings", PlatformSettings.from_env())
        url_field, token_field = SERVICE_FIELDS[service_id]
        services.configure(services.settings.__class__(
            **{
                **services.settings.__dict__,
                url_field: getattr(environment_settings, url_field),
                token_field: getattr(environment_settings, token_field),
            }
        ))
    return {"connection": _redacted(service_id, services, database)}
