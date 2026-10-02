from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.infrastructure.platforms import PlatformSettings, ServiceStatus


class SharedFilesAdapter:
    def __init__(self, settings: PlatformSettings) -> None:
        self.settings = settings

    def _root(self) -> Path | None:
        raw = self.settings.shared_files_root.strip()
        if not raw:
            return None
        return Path(raw).expanduser().resolve()

    def status(self) -> ServiceStatus:
        root = self._root()
        if root is None:
            return ServiceStatus(
                "shared-files",
                "Lyra Shared Files",
                "",
                False,
                "LYRA_SHARED_FILES_ROOT is not configured",
            )
        if self.settings.shared_file_max_bytes <= 0:
            return ServiceStatus(
                "shared-files",
                "Lyra Shared Files",
                str(root),
                False,
                "LYRA_SHARED_FILE_MAX_BYTES must be positive",
            )
        if not root.exists() or not root.is_dir():
            return ServiceStatus(
                "shared-files",
                "Lyra Shared Files",
                str(root),
                False,
                "configured shared files root is not a directory",
            )
        return ServiceStatus(
            "shared-files",
            "Lyra Shared Files",
            str(root),
            True,
            {
                "root": str(root),
                "max_bytes": self.settings.shared_file_max_bytes,
                "mode": "utf8-text-read-only",
            },
        )

    def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            raise ValueError("file.read requires a non-empty relative 'path'")

        requested = Path(raw_path)
        if requested.is_absolute():
            raise ValueError("file.read path must be relative")
        if any(part in {"", ".", ".."} or part.startswith(".") for part in requested.parts):
            raise ValueError("file.read path contains a forbidden path segment")

        root = self._root()
        if root is None:
            raise ValueError("shared files service is not configured")
        if self.settings.shared_file_max_bytes <= 0:
            raise ValueError("shared file max bytes must be positive")
        if not root.exists() or not root.is_dir():
            raise ValueError("shared files root is unavailable")

        try:
            candidate = (root / requested).resolve(strict=True)
            relative = candidate.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ValueError("requested shared file was not found or escaped the shared root") from exc

        if not candidate.is_file():
            raise ValueError("requested shared path is not a file")

        size = candidate.stat().st_size
        if size > self.settings.shared_file_max_bytes:
            raise ValueError(
                f"shared file exceeds {self.settings.shared_file_max_bytes} byte limit"
            )

        data = candidate.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("file.read supports UTF-8 text files only") from exc

        return {
            "path": relative.as_posix(),
            "content": text,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "encoding": "utf-8",
        }
