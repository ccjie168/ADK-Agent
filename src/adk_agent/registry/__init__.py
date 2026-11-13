"""Agent registry: immutable manifests pinned by digest."""

from __future__ import annotations

from .artifacts import ArtifactStoreError, FileArtifactStore, artifact_digest
from .file import FileAgentRegistry, RegistryConflict, RegistryError, RegistryIntegrityError
from .manifest import load_manifest, published_from
from .packaging import PackagingError, pack_agent, read_artifact_zip
from .reports import EvalReportConflict, FileEvalReportStore
from .signing import PublishUnavailable, load_private_key, sign_digest, verify_digest

__all__ = [
    "ArtifactStoreError",
    "EvalReportConflict",
    "FileArtifactStore",
    "PackagingError",
    "PublishUnavailable",
    "FileAgentRegistry",
    "FileEvalReportStore",
    "RegistryConflict",
    "RegistryError",
    "RegistryIntegrityError",
    "artifact_digest",
    "load_manifest",
    "load_private_key",
    "pack_agent",
    "published_from",
    "read_artifact_zip",
    "sign_digest",
    "verify_digest",
]
