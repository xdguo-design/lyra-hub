from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select

from app.domain.applications.models import (
    ApplicationPageConfig,
    ApplicationPageConfigUpdate,
    ApplicationSummary,
)
from app.domain.applications.registry import ManifestRegistry
from app.infrastructure.database import (
    ApplicationConfigRecord,
    ApplicationStateRecord,
    Database,
    record_audit,
)

router = APIRouter(tags=["page-configuration"])


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def _defaults(registry: ManifestRegistry, app_id: str) -> ApplicationPageConfig:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return ApplicationPageConfig(
        app_id=app_id,
        navigation_group=application.navigation_group,
        navigation_order=application.navigation_order,
        hidden=False,
        visible_roles=[],
        default_launch_mode="workspace",
    )


def _to_config(defaults: ApplicationPageConfig, record: ApplicationConfigRecord | None) -> ApplicationPageConfig:
    if record is None:
        return defaults
    return ApplicationPageConfig(
        app_id=defaults.app_id,
        name_override=record.name_override,
        navigation_group=record.navigation_group or defaults.navigation_group,
        navigation_order=record.navigation_order if record.navigation_order is not None else defaults.navigation_order,
        hidden=record.hidden,
        visible_roles=record.visible_roles,
        default_launch_mode=record.default_launch_mode,
    )


def _parse_roles(value: str | None) -> set[str]:
    if not value:
        return {"admin"}
    return {role.strip() for role in value.split(",") if role.strip()}


def _can_see(config: ApplicationPageConfig, roles: set[str]) -> bool:
    if "admin" in roles or not config.visible_roles:
        return True
    return bool(roles.intersection(config.visible_roles))


@router.get("/page-config", response_model=list[ApplicationPageConfig])
def list_page_configuration(
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> list[ApplicationPageConfig]:
    with database.session() as session:
        records = {item.app_id: item for item in session.scalars(select(ApplicationConfigRecord)).all()}
        return [_to_config(_defaults(registry, app.id), records.get(app.id)) for app in registry.list()]


@router.patch("/page-config/{app_id}", response_model=ApplicationPageConfig)
def update_page_configuration(
    app_id: str,
    request: ApplicationPageConfigUpdate,
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> ApplicationPageConfig:
    defaults = _defaults(registry, app_id)
    with database.session() as session:
        record = session.get(ApplicationConfigRecord, app_id)
        if record is None:
            record = ApplicationConfigRecord(
                app_id=app_id,
                navigation_group=defaults.navigation_group,
                navigation_order=defaults.navigation_order,
                hidden=defaults.hidden,
                visible_roles_json="[]",
                default_launch_mode=defaults.default_launch_mode,
            )
            session.add(record)

        before = _to_config(defaults, record).model_dump()
        fields = request.model_fields_set
        if "name_override" in fields:
            record.name_override = request.name_override or None
        if "navigation_group" in fields:
            record.navigation_group = request.navigation_group or defaults.navigation_group
        if "navigation_order" in fields:
            record.navigation_order = request.navigation_order if request.navigation_order is not None else defaults.navigation_order
        if "hidden" in fields and request.hidden is not None:
            record.hidden = request.hidden
        if "visible_roles" in fields:
            roles = sorted({role.strip() for role in (request.visible_roles or []) if role.strip()})
            record.visible_roles_json = json.dumps(roles, ensure_ascii=False)
        if "default_launch_mode" in fields:
            record.default_launch_mode = request.default_launch_mode or "workspace"

        after = _to_config(defaults, record).model_dump()
        if before != after:
            record_audit(
                session,
                action="page-config.updated",
                target_type="application",
                target_id=app_id,
                payload={"before": before, "after": after},
            )
        session.commit()
        session.refresh(record)
        return _to_config(defaults, record)


@router.get("/navigation", response_model=list[ApplicationSummary])
def navigation(
    x_lyra_roles: str | None = Header(default=None, alias="X-Lyra-Roles"),
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> list[ApplicationSummary]:
    roles = _parse_roles(x_lyra_roles)
    with database.session() as session:
        states = {item.app_id: item for item in session.scalars(select(ApplicationStateRecord)).all()}
        configs = {item.app_id: item for item in session.scalars(select(ApplicationConfigRecord)).all()}
        result: list[ApplicationSummary] = []
        for application in registry.list():
            defaults = _defaults(registry, application.id)
            config = _to_config(defaults, configs.get(application.id))
            state = states.get(application.id)
            enabled = state.enabled if state is not None else True
            if not enabled or config.hidden or not _can_see(config, roles):
                continue
            result.append(
                application.model_copy(
                    update={
                        "name": config.name_override or application.name,
                        "navigation_group": config.navigation_group,
                        "navigation_order": config.navigation_order,
                        "hidden": config.hidden,
                        "visible_roles": config.visible_roles,
                        "default_launch_mode": config.default_launch_mode,
                        "enabled": enabled,
                    }
                )
            )
        return sorted(result, key=lambda item: (item.navigation_order, item.name))
