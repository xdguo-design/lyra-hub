from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApplicationSummary(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""
    category: str = ""
    icon: str | None = None
    standalone_url: str
    workspace_path: str
    integration_type: str
    navigation_order: int = 100
    enabled: bool = True


class ApplicationDetail(ApplicationSummary):
    capabilities_consumed: list[str] = Field(default_factory=list)
    capabilities_provided: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    manifest: dict[str, Any]


class ApplicationUpdate(BaseModel):
    enabled: bool


class ApplicationLaunch(BaseModel):
    app_id: str
    mode: str
    url: str


class ManifestValidationRequest(BaseModel):
    manifest: dict[str, Any]


class ManifestValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: str
    payload: dict[str, Any]
    created_at: datetime
