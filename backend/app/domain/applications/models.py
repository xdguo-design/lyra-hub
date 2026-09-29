from __future__ import annotations

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


class ManifestValidationRequest(BaseModel):
    manifest: dict[str, Any]


class ManifestValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
