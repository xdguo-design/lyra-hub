from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.applications.models import (
    ApplicationDetail,
    ApplicationSummary,
    ManifestValidationRequest,
    ManifestValidationResult,
)
from app.domain.applications.registry import ManifestRegistry

router = APIRouter(prefix="/applications", tags=["applications"])


def get_registry() -> ManifestRegistry:
    raise RuntimeError("Application registry dependency was not configured")


@router.get("", response_model=list[ApplicationSummary])
def list_applications(registry: ManifestRegistry = Depends(get_registry)) -> list[ApplicationSummary]:
    return registry.list()


@router.get("/{app_id}", response_model=ApplicationDetail)
def get_application(app_id: str, registry: ManifestRegistry = Depends(get_registry)) -> ApplicationDetail:
    application = registry.get(app_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.post("/validate/manifest", response_model=ManifestValidationResult)
def validate_manifest(
    request: ManifestValidationRequest,
    registry: ManifestRegistry = Depends(get_registry),
) -> ManifestValidationResult:
    errors = registry.validate(request.manifest)
    return ManifestValidationResult(valid=not errors, errors=errors)
