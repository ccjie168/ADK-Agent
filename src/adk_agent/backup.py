"""Create and restore gzip tar backups of file-based state."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_VERSION = 1

_KINDS = frozenset({"registry", "approvals", "audit"})
_CHUNK = 1024 * 1024


class BackupError(RuntimeError):
    """A backup could not be created or restored."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_files(path: Path) -> list[tuple[Path, str]]:
    prefix = path.name + "."
    siblings = [
        sibling
        for sibling in path.parent.iterdir()
        if sibling.is_file()
        and sibling.name.startswith(prefix)
        and sibling.name[len(prefix) :].isdigit()
    ]
    files = [path, *sorted(siblings)]
    return [(file, f"audit/{file.name}") for file in files]


def _tree_files(kind: str, path: Path) -> list[tuple[Path, str]]:
    return [
        (child, f"{kind}/{child.relative_to(path).as_posix()}")
        for child in sorted(path.rglob("*"))
        if child.is_file()
    ]


def create_backup(
    out: str | Path,
    sources: Sequence[tuple[str, str | Path]],
    *,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], str]:
    """Write a gzip tar of ``sources`` to ``out`` and return its manifest and digest."""
    if not sources:
        raise BackupError("at least one source is required")

    now = clock or (lambda: datetime.now(timezone.utc))
    selected: list[tuple[str, Path]] = []
    for kind, path in sources:
        if kind not in _KINDS:
            raise BackupError(f"unknown source kind: {kind}")
        source = Path(path)
        if not source.exists():
            raise BackupError(f"missing source: {kind}")
        if kind == "audit" and not source.is_file():
            raise BackupError(f"source is not a file: {kind}")
        if kind != "audit" and not source.is_dir():
            raise BackupError(f"source is not a directory: {kind}")
        selected.append((kind, source))

    entries: list[dict[str, Any]] = []
    with tarfile.open(Path(out), "w:gz") as archive:
        for kind, source in selected:
            files = _audit_files(source) if kind == "audit" else _tree_files(kind, source)
            entries.append(
                {
                    "kind": kind,
                    "files": len(files),
                    "bytes": sum(file.stat().st_size for file, _ in files),
                }
            )
            for file, arcname in files:
                archive.add(file, arcname=arcname)

        manifest: dict[str, Any] = {
            "version": BACKUP_VERSION,
            "created_at": now().astimezone(timezone.utc).isoformat(),
            "sources": entries,
        }
        payload = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    digest = _sha256(Path(out))
    with contextlib.suppress(OSError):
        os.chmod(out, 0o600)
    return manifest, digest


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise BackupError("manifest.json is missing")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("manifest.json is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != BACKUP_VERSION:
        raise BackupError("unsupported backup version")
    return manifest


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def restore_backup(archive: str | Path, dest: str | Path, *, force: bool = False) -> dict[str, Any]:
    """Extract ``archive`` into ``dest`` after validating its manifest."""
    archive_path = Path(archive)
    destination = Path(dest)
    if destination.exists() and not force and not _is_empty_dir(destination):
        raise BackupError("destination is not empty")

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".adk-restore-", dir=destination.parent))
    try:
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(tmp, filter="data")
            manifest = _load_manifest(tmp)
        except BackupError:
            raise
        except (tarfile.TarError, OSError, ValueError) as exc:
            raise BackupError(str(exc)) from exc
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    try:
        if destination.exists():
            if force:
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            else:
                destination.rmdir()
        os.replace(tmp, destination)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise BackupError(str(exc)) from exc
    return manifest
