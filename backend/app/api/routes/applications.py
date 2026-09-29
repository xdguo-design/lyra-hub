from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.applications.models import (
    ApplicationDetail,
    ApplicationLaunch,
    ApplicationSummary,
    ApplicationUpdate,
    ManifestValidationRequest,
    ManifestValidationResult,
)
from app.domain.applications.registry import ManifestRegistry
from app.infrastructure.database import (
    ApplicationConfigRecord,
    ApplicationStateRecord,
    Database,
    record_audit,
)

router = APIRouter(prefix="/applications", tags=["applications"])


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def _state(session: Session, app_id: str) -> ApplicationStateRecord | None:
    return session.get(ApplicationStateRecord, app_id)


def _config(session: Session, app_id: str) -> ApplicationConfigRecord | None:
    return session.get(ApplicationConfigRecord, app_id)


def _apply_effective(
    application: ApplicationSummary | ApplicationDetail,
    state_record: ApplicationStateRecord | None,
    config_record: ApplicationConfigRecord | None,
) -> ApplicationSummary | ApplicationDetail:
    update: dict[str, object] = {}
    if state_record is not None:
        update["enabled"] = state_record.enabled
    if config_record is not None:
        if config_record.name_override:
            update["name"] = config_record.name_override
        if config_record.navigation_group:
            update["navigation_group"] = config_record.navigation_group
        if config_record.navigation_order is not None:
            update["navigation_order"] = config_record.navigation_order
        update["hidden"] = config_record.hidden
        update["visible_roles"] = config_record.visible_roles
        update["default_launch_mode"] = config_record.default_launch_mode
    return application.model_copy(update=update)


@router.get("", response_model=list[ApplicationSummary])
def list_applications(
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> list[ApplicationSummary]:
    with database.session() as session:
        states = {item.app_id: item for item in session.scalars(select(ApplicationStateRecord)).all()}
        configs = {item.app_id: item for item in session.scalars(select(ApplicationConfigRecord)).all()}
        apps = [
            ApplicationSummary.model_validate(
                _apply_effective(application, states.get(application.id), configs.get(application.id))
            )
            for application in registry.list()
        ]
        return sorted(apps, key=lambda item: (item.navigation_order, item.name))


@router.post("/validate/manifest", response_model=ManifestValidationResult)
def validate_manifest(
    request: ManifestValidationRequest,
    registry: ManifestRegistry = Depends(get_registry),
) -> ManifestValidationResult:
    errors = registry.validate(request.manifest)
    return ManifestValidationResult(valid=not errors, errors=errors)


@router.get("/{app_id}", response_model=ApplicationDetail)
def get_application(
    app_id: str,
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> ApplicationDetail:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    with database.session() as session:
        return ApplicationDetail.model_validate(
            _apply_effective(application, _state(session, app_id), _config(session, app_id))
        )


@router.patch("/{app_id}", response_model=ApplicationDetail)
def update_application(
    app_id: str,
    request: ApplicationUpdate,
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> ApplicationDetail:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    with database.session() as session:
        state_record = _state(session, app_id)
        previous_enabled = state_record.enabled if state_record is not None else True
        if state_record is None:
            state_record = ApplicationStateRecord(app_id=app_id, enabled=request.enabled)
            session.add(state_record)
        else:
            state_record.enabled = request.enabled

        if previous_enabled != request.enabled:
            record_audit(
                session,
                action="application.enabled" if request.enabled else "application.disabled",
                target_type="application",
                target_id=app_id,
                payload={"enabled": request.enabled, "previous_enabled": previous_enabled},
            )
        session.commit()
        session.refresh(state_record)
        return ApplicationDetail.model_validate(
            _apply_effective(application, state_record, _config(session, app_id))
        )


@router.post("/{app_id}/launch", response_model=ApplicationLaunch)
def launch_application(
    app_id: str,
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> ApplicationLaunch:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    with database.session() as session:
        state_record = _state(session, app_id)
        config_record = _config(session, app_id)
        if state_record is not None and not state_record.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application is disabled and cannot be launched from Hub",
            )
        effective = ApplicationDetail.model_validate(_apply_effective(application, state_record, config_record))

    allowed_origins: list[str] = []
    if effective.default_launch_mode == "standalone":
        url = effective.standalone_url
    else:
        integration = effective.manifest["workspace"]["integration"]
        url = integration.get("url") or effective.standalone_url
        if effective.integration_type == "iframe":
            allowed_origins = [str(item).rstrip("/") for item in integration.get("allowedOrigins", [])]
            parsed = urlsplit(url)
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
            if not allowed_origins or origin not in allowed_origins:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": "iframe_origin_not_allowed",
                        "origin": origin,
                        "allowed_origins": allowed_origins,
                    },
                )

    return ApplicationLaunch(
        app_id=app_id,
        launch_mode=effective.default_launch_mode,
        integration_type=effective.integration_type,
        url=url,
        workspace_path=effective.workspace_path,
        allowed_origins=allowed_origins,
    )
