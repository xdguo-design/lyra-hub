from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.domain.plugins.models import (
    PluginDetail,
    PluginSummary,
    PluginUpdate,
    PluginValidationRequest,
    PluginValidationResult,
)
from app.domain.plugins.registry import PluginRegistry
from app.infrastructure.database import Database, PluginStateRecord, record_audit

router = APIRouter(prefix="/plugins", tags=["plugins"])


def get_registry() -> PluginRegistry:
    raise RuntimeError("Plugin registry dependency was not configured")


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def _effective(plugin: PluginDetail, state_record: PluginStateRecord | None) -> PluginDetail:
    if state_record is None:
        return plugin
    return plugin.model_copy(
        update={
            "enabled": state_record.enabled,
            "granted_permissions": state_record.granted_permissions,
        }
    )


@router.get("", response_model=list[PluginSummary])
def list_plugins(
    application_id: str | None = Query(default=None),
    registry: PluginRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> list[PluginSummary]:
    with database.session() as session:
        states = {item.plugin_id: item for item in session.scalars(select(PluginStateRecord)).all()}
        result: list[PluginSummary] = []
        for plugin in registry.list():
            detail = registry.get(plugin.id)
            if detail is None:
                continue
            effective = _effective(detail, states.get(plugin.id))
            if application_id and application_id not in effective.target_applications:
                continue
            result.append(PluginSummary.model_validate(effective))
        return result


@router.post("/validate/manifest", response_model=PluginValidationResult)
def validate_plugin_manifest(
    request: PluginValidationRequest,
    registry: PluginRegistry = Depends(get_registry),
) -> PluginValidationResult:
    errors = registry.validate(request.manifest)
    return PluginValidationResult(valid=not errors, errors=errors)


@router.get("/{plugin_id}", response_model=PluginDetail)
def get_plugin(
    plugin_id: str,
    registry: PluginRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> PluginDetail:
    plugin = registry.get(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    with database.session() as session:
        return _effective(plugin, session.get(PluginStateRecord, plugin_id))


@router.patch("/{plugin_id}", response_model=PluginDetail)
def update_plugin(
    plugin_id: str,
    request: PluginUpdate,
    registry: PluginRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> PluginDetail:
    plugin = registry.get(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")

    with database.session() as session:
        state_record = session.get(PluginStateRecord, plugin_id)
        previous = _effective(plugin, state_record)

        granted_permissions = (
            sorted({item.strip() for item in request.granted_permissions if item.strip()})
            if request.granted_permissions is not None
            else previous.granted_permissions
        )
        enabled = request.enabled if request.enabled is not None else previous.enabled

        missing = sorted(set(plugin.permissions) - set(granted_permissions))
        if enabled and missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "plugin_permissions_missing", "permissions": missing},
            )

        if state_record is None:
            state_record = PluginStateRecord(plugin_id=plugin_id)
            session.add(state_record)
        state_record.enabled = enabled
        state_record.granted_permissions_json = json.dumps(granted_permissions, ensure_ascii=False)

        after = plugin.model_copy(
            update={"enabled": enabled, "granted_permissions": granted_permissions}
        )
        if previous.model_dump(exclude={"manifest"}) != after.model_dump(exclude={"manifest"}):
            action = "plugin.config.updated"
            if previous.enabled != enabled:
                action = "plugin.enabled" if enabled else "plugin.disabled"
            record_audit(
                session,
                action=action,
                target_type="plugin",
                target_id=plugin_id,
                payload={
                    "enabled": enabled,
                    "granted_permissions": granted_permissions,
                },
            )
        session.commit()
        session.refresh(state_record)
        return _effective(plugin, state_record)
