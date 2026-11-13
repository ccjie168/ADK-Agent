"""Deterministic agent packaging (ADR-0008)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from ..core import MAX_ARTIFACT_BYTES, AgentManifest

_OPTIONAL_FILES = ("README.md", "requirements.txt")


class PackagingError(RuntimeError):
    """The source directory or archive cannot become an agent artifact."""


def _read_manifest(source: Path) -> AgentManifest:
    path = source / "manifest.json"
    if not path.is_file():
        raise PackagingError("artifact source has no manifest.json")
    try:
        return AgentManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PackagingError("artifact source has an invalid manifest.json") from exc


def pack_agent(source: str | Path, *, entrypoint: str = "agent.py") -> bytes:
    """Pack a project directory into a byte-identical zip."""
    root = Path(source)
    if not root.is_dir():
        raise PackagingError("artifact source must be a directory")
    _read_manifest(root)
    if not (root / entrypoint).is_file():
        raise PackagingError(f"artifact source has no {entrypoint}")
    names = {"manifest.json", entrypoint}
    names.update(name for name in _OPTIONAL_FILES if (root / name).is_file())
    files = {name: (root / name).read_bytes() for name in sorted(names)}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    data = buffer.getvalue()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise PackagingError("artifact exceeds the 8 MiB limit")
    return data


def read_artifact_zip(path: str | Path) -> tuple[bytes, AgentManifest]:
    """Read an artifact zip and its manifest without trusting either."""
    data = Path(path).read_bytes()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise PackagingError("artifact exceeds the 8 MiB limit")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            raw = archive.read("manifest.json")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise PackagingError("artifact has no readable manifest.json") from exc
    try:
        manifest = AgentManifest.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        raise PackagingError("artifact manifest is invalid") from exc
    return data, manifest


__all__ = ["PackagingError", "pack_agent", "read_artifact_zip"]
