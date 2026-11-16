"""Agent registry: immutable manifests pinned by digest."""

from __future__ import annotations

from ..core import (
    ConnectorConflict,
    ConnectorForbidden,
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
from .connector_health import ConnectorHealth, check_connector
from .connector_requests import FileConnectorRequestStore
from .connector_requests_postgres import PostgresConnectorRequestStore
from .connectors import FileConnectorStore
from .connectors_client import HttpConnectorStore
from .connectors_postgres import PostgresConnectorStore
from .credentials import FileCredentialStore, credential_is_bound
from .credentials_postgres import PostgresCredentialStore
from .file import FileAgentRegistry, RegistryConflict, RegistryError, RegistryIntegrityError
from .lifecycle import FileAgentLifecycleStore
from .lifecycle_postgres import PostgresAgentLifecycleStore
from .loader import ArtifactLoadError, InProcessArtifactLoader, load_agent
from .manifest import load_manifest, published_from
from .packaging import PackagingError, pack_agent, pack_files, read_artifact_zip
from .paths import UnsafePath, safe_join
from .peer_grants import FilePeerGrantStore
from .peer_grants_postgres import PostgresPeerGrantStore
from .peers import FilePeerStore
from .peers_postgres import PostgresPeerStore
from .postgres import PostgresAgentRegistry, RegistryStoreUnavailable
from .refs import RefError, load_registry_agents, parse_agent_ref
from .remote_agents import FileRemoteAgentStore, fetch_agent_card
from .remote_agents_postgres import PostgresRemoteAgentStore
from .reports import EvalReportConflict, FileEvalReportStore
from .reports_postgres import PostgresEvalReportStore
from .signing import PublishUnavailable, load_private_key, sign_digest, verify_digest
from .tool_grants import FileToolGrantStore
from .tool_grants_postgres import PostgresToolGrantStore
from .trigger_runs import FileTriggerFireStore
from .trigger_runs_postgres import PostgresTriggerFireStore
from .triggers import FileTriggerStore
from .triggers_postgres import PostgresTriggerStore
from .trust import ArtifactTrustError, TrustStore

__all__ = [
    "ArtifactLoadError",
    "ArtifactStoreError",
    "ArtifactTrustError",
    "EvalReportConflict",
    "ConnectorConflict",
    "ConnectorForbidden",
    "ConnectorHealth",
    "ConnectorNotFound",
    "FileAgentLifecycleStore",
    "FileConnectorRequestStore",
    "FileConnectorStore",
    "FileCredentialStore",
    "FileArtifactStore",
    "FilePeerGrantStore",
    "FilePeerStore",
    "FileRemoteAgentStore",
    "FileToolGrantStore",
    "FileTriggerFireStore",
    "FileTriggerStore",
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
    "PostgresConnectorRequestStore",
    "PostgresConnectorStore",
    "PostgresCredentialStore",
    "PostgresEvalReportStore",
    "PostgresPeerGrantStore",
    "PostgresPeerStore",
    "PostgresRemoteAgentStore",
    "PostgresToolGrantStore",
    "PostgresTriggerFireStore",
    "PostgresTriggerStore",
    "PublishUnavailable",
    "FileAgentRegistry",
    "FileEvalReportStore",
    "HttpAgentLifecycleStore",
    "HttpAgentRegistry",
    "HttpConnectorStore",
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
    "UnsafePath",
    "artifact_digest",
    "check_connector",
    "credential_is_bound",
    "fetch_agent_card",
    "load_agent",
    "load_manifest",
    "load_private_key",
    "load_registry_agents",
    "pack_agent",
    "pack_files",
    "parse_agent_ref",
    "published_from",
    "read_artifact_zip",
    "safe_join",
    "sign_digest",
    "verify_digest",
]
