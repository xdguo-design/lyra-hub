from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from .models import PluginContribution, PluginDetail, PluginSummary


class PluginRegistry:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.manifest_dir = repo_root / "examples" / "plugins"
        schema_path = repo_root / "contracts" / "plugin-manifest.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def validate(self, manifest: dict[str, Any]) -> list[str]:
        errors = sorted(self.validator.iter_errors(manifest), key=lambda error: list(error.path))
        return [self._format_error(error) for error in errors]

    def list(self) -> list[PluginSummary]:
        return [
            PluginSummary(**item.model_dump(exclude={"manifest"}))
            for item in sorted(self._load_valid_plugins(), key=lambda plugin: plugin.name)
        ]

    def get(self, plugin_id: str) -> PluginDetail | None:
        for plugin in self._load_valid_plugins():
            if plugin.id == plugin_id:
                return plugin
        return None

    def _load_valid_plugins(self) -> list[PluginDetail]:
        plugins: list[PluginDetail] = []
        if not self.manifest_dir.exists():
            return plugins
        for path in sorted(self.manifest_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or self.validate(payload):
                continue
            plugins.append(self._to_detail(payload))
        return plugins

    @staticmethod
    def _to_detail(manifest: dict[str, Any]) -> PluginDetail:
        capabilities = manifest.get("capabilities") or {}
        contributions = manifest.get("contributes") or {}
        return PluginDetail(
            id=manifest["id"],
            name=manifest["name"],
            version=manifest["version"],
            description=manifest.get("description", ""),
            target_applications=manifest.get("targetApplications", []),
            permissions=manifest.get("permissions", []),
            capabilities_consumed=capabilities.get("consumes", []),
            contributions=PluginContribution.model_validate(contributions),
            enabled=False,
            granted_permissions=[],
            manifest=manifest,
        )

    @staticmethod
    def _format_error(error: Any) -> str:
        path = ".".join(str(part) for part in error.path)
        return f"{path}: {error.message}" if path else error.message
