from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PluginContribution(BaseModel):
    widgets: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    navigation: list[dict[str, Any]] = Field(default_factory=list)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    slots: list[dict[str, Any]] = Field(default_factory=list)


class PluginSummary(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""
    target_applications: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    capabilities_consumed: list[str] = Field(default_factory=list)
    contributions: PluginContribution = Field(default_factory=PluginContribution)
    enabled: bool = False
    granted_permissions: list[str] = Field(default_factory=list)


class PluginDetail(PluginSummary):
    manifest: dict[str, Any]


class PluginUpdate(BaseModel):
    enabled: bool | None = None
    granted_permissions: list[str] | None = None


class PluginValidationRequest(BaseModel):
    manifest: dict[str, Any]


class PluginValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
