from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from .models import ApplicationDetail, ApplicationSummary


class ManifestRegistry:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.manifest_dir = repo_root / "examples" / "manifests"
        schema_path = repo_root / "contracts" / "app-manifest.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def validate(self, manifest: dict[str, Any]) -> list[str]:
        errors = sorted(self.validator.iter_errors(manifest), key=lambda error: list(error.path))
        return [self._format_error(error) for error in errors]

    def list(self) -> list[ApplicationSummary]:
        apps = [self._to_detail(manifest) for manifest in self._load_valid_manifests()]
        return [
            ApplicationSummary(**app.model_dump(exclude={"capabilities_consumed", "capabilities_provided", "permissions", "health_url", "manifest"}))
            for app in sorted(apps, key=lambda item: (item.navigation_order, item.name))
        ]

    def get(self, app_id: str) -> ApplicationDetail | None:
        for manifest in self._load_valid_manifests():
            if manifest.get("id") == app_id:
                return self._to_detail(manifest)
        return None

    def _load_valid_manifests(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for path in sorted(self.manifest_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            errors = self.validate(payload)
            if errors:
                continue
            manifests.append(payload)
        return manifests

    def _to_detail(self, manifest: dict[str, Any]) -> ApplicationDetail:
        standalone = manifest["standalone"]
        workspace = manifest["workspace"]
        integration = workspace["integration"]
        navigation = manifest.get("navigation") or {}
        capabilities = manifest.get("capabilities") or {}
        health = manifest.get("health") or {}
        return ApplicationDetail(
            id=manifest["id"],
            name=manifest["name"],
            version=manifest["version"],
            description=manifest.get("description", ""),
            category=manifest.get("category", ""),
            icon=manifest.get("icon"),
            standalone_url=standalone["url"],
            workspace_path=workspace["path"],
            integration_type=integration["type"],
            navigation_order=navigation.get("order", 100),
            navigation_group=navigation.get("group", "Applications"),
            enabled=True,
            hidden=False,
            visible_roles=[],
            default_launch_mode="workspace",
            capabilities_consumed=capabilities.get("consumes", []),
            capabilities_provided=capabilities.get("provides", []),
            permissions=manifest.get("permissions", []),
            health_url=health.get("url"),
            manifest=manifest,
        )

    @staticmethod
    def _format_error(error: Any) -> str:
        path = ".".join(str(part) for part in error.path)
        return f"{path}: {error.message}" if path else error.message
