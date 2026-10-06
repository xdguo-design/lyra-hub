from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.platforms import PlatformSettings, SharedFilesAdapter


def _adapter(root: Path, *, max_bytes: int = 1024) -> SharedFilesAdapter:
    return SharedFilesAdapter(
        PlatformSettings(
            shared_files_root=str(root),
            shared_file_max_bytes=max_bytes,
        )
    )


def test_shared_files_is_disabled_without_explicit_root() -> None:
    adapter = SharedFilesAdapter(PlatformSettings())

    status = adapter.status()

    assert status.reachable is False
    assert "not configured" in str(status.detail)


def test_shared_file_read_returns_utf8_content_and_digest(tmp_path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    (root / "notes").mkdir()
    (root / "notes" / "chapter.md").write_text("第一章\nhello", encoding="utf-8")
    adapter = _adapter(root)

    result = adapter.read({"path": "notes/chapter.md"})

    assert result["path"] == "notes/chapter.md"
    assert result["content"] == "第一章\nhello"
    assert result["encoding"] == "utf-8"
    assert result["size_bytes"] > 0
    assert len(result["sha256"]) == 64


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        ".env",
        "hidden/.secret",
    ],
)
def test_shared_file_read_rejects_forbidden_segments(tmp_path, path: str) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    adapter = _adapter(root)

    with pytest.raises(ValueError, match="forbidden path segment"):
        adapter.read({"path": path})


def test_shared_file_read_rejects_absolute_path(tmp_path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    adapter = _adapter(root)

    with pytest.raises(ValueError, match="must be relative"):
        adapter.read({"path": str(outside.resolve())})


def test_shared_file_read_rejects_symlink_escape(tmp_path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable in this environment: {exc}")
    adapter = _adapter(root)

    with pytest.raises(ValueError, match="escaped the shared root"):
        adapter.read({"path": "link.txt"})


def test_shared_file_read_enforces_size_limit(tmp_path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    (root / "large.txt").write_text("abcdef", encoding="utf-8")
    adapter = _adapter(root, max_bytes=5)

    with pytest.raises(ValueError, match="exceeds 5 byte limit"):
        adapter.read({"path": "large.txt"})


def test_shared_file_read_rejects_non_utf8_content(tmp_path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    (root / "binary.dat").write_bytes(b"\xff\xfe\xfd")
    adapter = _adapter(root)

    with pytest.raises(ValueError, match="UTF-8"):
        adapter.read({"path": "binary.dat"})
