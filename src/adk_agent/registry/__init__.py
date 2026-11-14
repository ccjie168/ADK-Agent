"""Agent registry: immutable manifests pinned by digest."""

from __future__ import annotations

from ..core import (
    ConnectorConflict,
    ConnectorNotFound,
    GrantRequestConflict,
    GrantRequestError,
    GrantRequestExpired,
    GrantRequestNotFound,
    GrantStoreError,
    GrantStoreUnavailable,
)
from .artifacts import ArtifactStoreError, FileArtifactStore, artifact_digest
from .client import (
    HttpAgentLifecycleStore,
    HttpAgentRegistry,
    HttpEvalReportStore,
    RegistryForbidden,
    RegistryRejected,
    RegistryServiceUnavailable,
)
from .connectors import FileConnectorStore
from .connectors_postgres import PostgresConnectorStore
from .file import FileAgentRegistry, RegistryConflict, RegistryError, RegistryIntegrityError
from .lifecycle import FileAgentLifecycleStore
from .lifecycle_postgres import PostgresAgentLifecycleStore
from .loader import ArtifactLoadError, InProcessArtifactLoader, load_agent
from .manifest import load_manifest, published_from
from .packaging import PackagingError, pack_agent, read_artifact_zip
from .postgres import PostgresAgentRegistry, RegistryStoreUnavailable
from .refs import RefError, load_registry_agents, parse_agent_ref
from .reports import EvalReportConflict, FileEvalReportStore
from .reports_postgres import PostgresEvalReportStore
from .signing import PublishUnavailable, load_private_key, sign_digest, verify_digest
from .tool_grants import FileToolGrantStore
from .tool_grants_postgres import PostgresToolGrantStore
from .trust import ArtifactTrustError, TrustStore

__all__ = [
    "ArtifactLoadError",
    "ArtifactStoreError",
    "ArtifactTrustError",
    "EvalReportConflict",
    "ConnectorConflict",
    "ConnectorNotFound",
    "FileAgentLifecycleStore",
    "FileConnectorStore",
    "FileArtifactStore",
    "FileToolGrantStore",
    "GrantRequestConflict",
    "GrantRequestError",
    "GrantRequestExpired",
    "GrantRequestNotFound",
    "GrantStoreError",
    "GrantStoreUnavailable",
    "InProcessArtifactLoader",
    "PackagingError",
    "PostgresAgentLifecycleStore",
    "PostgresAgentRegistry",
    "PostgresConnectorStore",
    "PostgresEvalReportStore",
    "PostgresToolGrantStore",
    "PublishUnavailable",
    "FileAgentRegistry",
    "FileEvalReportStore",
    "HttpAgentLifecycleStore",
    "HttpAgentRegistry",
    "HttpEvalReportStore",
    "RefError",
    "RegistryConflict",
    "RegistryError",
    "RegistryForbidden",
    "RegistryIntegrityError",
    "RegistryRejected",
    "RegistryServiceUnavailable",
    "RegistryStoreUnavailable",
    "TrustStore",
    "artifact_digest",
    "load_agent",
    "load_manifest",
    "load_private_key",
    "load_registry_agents",
    "pack_agent",
    "parse_agent_ref",
    "published_from",
    "read_artifact_zip",
    "sign_digest",
    "verify_digest",
]
