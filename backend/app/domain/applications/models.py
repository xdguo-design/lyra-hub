from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
    navigation_group: str = "Applications"
    enabled: bool = True
    hidden: bool = False
    visible_roles: list[str] = Field(default_factory=list)
    default_launch_mode: Literal["workspace", "standalone"] = "workspace"


class ApplicationDetail(ApplicationSummary):
    capabilities_consumed: list[str] = Field(default_factory=list)
    capabilities_provided: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    health_url: str | None = None
    manifest: dict[str, Any]


class ApplicationUpdate(BaseModel):
    enabled: bool


class ApplicationLaunch(BaseModel):
    app_id: str
    launch_mode: Literal["workspace", "standalone"]
    integration_type: str
    url: str
    workspace_path: str


class ApplicationPageConfig(BaseModel):
    app_id: str
    name_override: str | None = None
    navigation_group: str
    navigation_order: int
    hidden: bool
    visible_roles: list[str] = Field(default_factory=list)
    default_launch_mode: Literal["workspace", "standalone"] = "workspace"


class ApplicationPageConfigUpdate(BaseModel):
    name_override: str | None = Field(default=None, max_length=120)
    navigation_group: str | None = Field(default=None, max_length=80)
    navigation_order: int | None = Field(default=None, ge=-10000, le=10000)
    hidden: bool | None = None
    visible_roles: list[str] | None = None
    default_launch_mode: Literal["workspace", "standalone"] | None = None


class ApplicationPageItemConfig(BaseModel):
    app_id: str
    page_id: str
    title: str
    path: str
    navigation_order: int
    hidden: bool = False
    visible_roles: list[str] = Field(default_factory=list)


class ApplicationPageItemUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    navigation_order: int | None = Field(default=None, ge=-10000, le=10000)
    hidden: bool | None = None
    visible_roles: list[str] | None = None


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
