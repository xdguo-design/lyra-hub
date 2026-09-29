from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.infrastructure.database import ApplicationStateRecord, Database, record_audit

router = APIRouter(prefix="/applications", tags=["applications"])


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


def get_database() -> Database:
    raise RuntimeError("Database dependency was not configured")


def _state(session: Session, app_id: str) -> ApplicationStateRecord | None:
    return session.get(ApplicationStateRecord, app_id)


def _apply_state(
    application: ApplicationSummary | ApplicationDetail,
    state_record: ApplicationStateRecord | None,
) -> ApplicationSummary | ApplicationDetail:
    if state_record is None:
        return application
    return application.model_copy(update={"enabled": state_record.enabled})


@router.get("", response_model=list[ApplicationSummary])
def list_applications(
    registry: ManifestRegistry = Depends(get_registry),
    database: Database = Depends(get_database),
) -> list[ApplicationSummary]:
    with database.session() as session:
        return [
            ApplicationSummary.model_validate(_apply_state(application, _state(session, application.id)))
            for application in registry.list()
        ]


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
        return ApplicationDetail.model_validate(_apply_state(application, _state(session, app_id)))


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
        return ApplicationDetail.model_validate(_apply_state(application, state_record))


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
        if state_record is not None and not state_record.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application is disabled and cannot be launched from Hub",
            )

    return ApplicationLaunch(app_id=app_id, mode=application.integration_type, url=application.standalone_url)
