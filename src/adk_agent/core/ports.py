"""Ports the adapters implement. Core depends on these, never on adapters."""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Literal, Protocol

from .approval import ApprovalDecision, ApprovalRequest
from .artifact import AgentArtifact
from .audit import AuditEvent
from .connector_requests import ConnectorRequest, ConnectorRequestStatus
from .credentials import CredentialBinding
from .eval import EvalReport
from .identity import Principal
from .invocation import Invocation
from .lifecycle import AgentLifecycle, LifecycleStatus
from .manifest import AgentRef, ModelPolicy, PublishedAgent
from .model import EmbeddingRequest, EmbeddingResponse, ModelRequest, ModelResponse
from .peers import PeerGrant, PeerIdentity
from .policy import DataClass, PolicyDecision
from .quota import QuotaPolicy
from .remote_agents import RemoteAgent
from .tool import ToolRequest, ToolResponse
from .tool_grants import GrantStatus, ToolGrantRequest
from .tool_idempotency import ToolExecutionRecord, ToolExecutionStatus
from .trigger_runs import TriggerFire, TriggerFireStatus
from .triggers import AgentTrigger


class AgentRegistry(Protocol):
    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None: ...

    async def publish(self, agent: PublishedAgent) -> PublishedAgent: ...

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]: ...

    async def tenants(self) -> builtins.list[str]: ...


class AgentLifecycleStore(Protocol):
    async def get(self, tenant: str, agent_id: str, version: str) -> AgentLifecycle: ...

    async def set(
        self,
        tenant: str,
        agent_id: str,
        version: str,
        *,
        status: LifecycleStatus,
        changed_by: str,
        reason: str,
    ) -> AgentLifecycle: ...


class ToolGrantStore(Protocol):
    async def add(self, request: ToolGrantRequest) -> ToolGrantRequest: ...

    async def get(self, request_id: str) -> ToolGrantRequest | None: ...

    async def list(
        self,
        tenant: str,
        *,
        status: GrantStatus | None = None,
        now: datetime | None = None,
    ) -> builtins.list[ToolGrantRequest]: ...

    async def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> ToolGrantRequest: ...

    async def cancel(
        self,
        request_id: str,
        *,
        by: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> ToolGrantRequest: ...

    async def active(
        self,
        tenant: str,
        agent_id: str,
        version: str,
        digest: str,
        tool_id: str,
        now: datetime | None = None,
    ) -> bool: ...


class CredentialStore(Protocol):
    async def add(self, binding: CredentialBinding) -> CredentialBinding: ...

    async def replace_wrapped(
        self,
        tenant: str,
        credential_id: str,
        wrapped_secret: dict[str, Any],
        secret_key_id: str,
    ) -> CredentialBinding: ...

    async def get(self, tenant: str, credential_id: str) -> CredentialBinding | None: ...

    async def list(self, tenant: str) -> builtins.list[CredentialBinding]: ...

    async def disable(self, tenant: str, credential_id: str, *, by: str) -> CredentialBinding: ...


class TriggerStore(Protocol):
    async def add(self, trigger: AgentTrigger) -> AgentTrigger: ...

    async def get(self, tenant: str, trigger_id: str) -> AgentTrigger | None: ...

    async def list(self, tenant: str) -> builtins.list[AgentTrigger]: ...

    async def list_all(self) -> builtins.list[AgentTrigger]: ...

    async def disable(self, tenant: str, trigger_id: str, *, by: str) -> AgentTrigger: ...


class TriggerFireStore(Protocol):
    async def claim(self, fire: TriggerFire) -> TriggerFire: ...

    async def finish(
        self,
        tenant: str,
        trigger_id: str,
        idempotency_key: str,
        *,
        status: TriggerFireStatus,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> TriggerFire: ...

    async def get(
        self, tenant: str, trigger_id: str, idempotency_key: str
    ) -> TriggerFire | None: ...


class ToolIdempotencyStore(Protocol):
    async def claim(self, record: ToolExecutionRecord) -> ToolExecutionRecord: ...

    async def finish(
        self,
        tenant: str,
        tool_id: str,
        idempotency_key: str,
        *,
        status: ToolExecutionStatus,
        output: Any = None,
        data_classes: builtins.list[DataClass] | None = None,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> ToolExecutionRecord: ...

    async def get(
        self, tenant: str, tool_id: str, idempotency_key: str
    ) -> ToolExecutionRecord | None: ...

    async def release(self, tenant: str, tool_id: str, idempotency_key: str) -> None: ...

    async def aclose(self) -> None: ...


class ConnectorRequestStore(Protocol):
    async def add(self, record: ConnectorRequest) -> ConnectorRequest: ...

    async def get(self, request_id: str) -> ConnectorRequest | None: ...

    async def list(
        self,
        tenant: str,
        *,
        status: ConnectorRequestStatus | None = None,
    ) -> builtins.list[ConnectorRequest]: ...

    async def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str,
        registered_connector: str | None = None,
    ) -> ConnectorRequest: ...


class EvalReportStore(Protocol):
    async def put(
        self, tenant: str, agent_id: str, version: str, report: EvalReport
    ) -> EvalReport: ...

    async def get(self, tenant: str, agent_id: str, version: str) -> EvalReport | None: ...

    async def has(self, tenant: str, agent_id: str, version: str) -> bool: ...


class IdentityProvider(Protocol):
    async def resolve(self, credential: str) -> Principal: ...


class QuotaManager(Protocol):
    def reserve(self, tenant: str, policy: QuotaPolicy) -> AbstractAsyncContextManager[None]: ...


class ApprovalGate(Protocol):
    async def request(self, request: ApprovalRequest) -> ApprovalDecision: ...


class SecretProvider(Protocol):
    async def resolve(self, reference: str) -> str: ...


class PolicyEngine(Protocol):
    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision: ...


class AuditSink(Protocol):
    async def emit(self, event: AuditEvent) -> None: ...


class ArtifactStore(Protocol):
    async def put(self, artifact: AgentArtifact, data: bytes) -> None: ...

    async def get(self, digest: str) -> bytes | None: ...

    async def has(self, digest: str) -> bool: ...


class ArtifactLoader(Protocol):
    async def load(self, artifact: AgentArtifact, store: ArtifactStore) -> Any: ...


class PeerStore(Protocol):
    async def get(self, peer_id: str) -> PeerIdentity | None: ...

    async def get_by_subject(self, subject: str) -> PeerIdentity | None: ...

    async def list(self) -> builtins.list[PeerIdentity]: ...

    async def put(self, identity: PeerIdentity) -> PeerIdentity: ...


class PeerGrantStore(Protocol):
    async def get(self, peer_id: str, agent_id: str) -> PeerGrant | None: ...

    async def list(self) -> builtins.list[PeerGrant]: ...

    async def put(self, grant: PeerGrant) -> PeerGrant: ...

    async def delete(self, peer_id: str, agent_id: str) -> bool: ...


class RemoteAgentStore(Protocol):
    async def get(self, remote_id: str) -> RemoteAgent | None: ...

    async def list(self) -> builtins.list[RemoteAgent]: ...

    async def put(self, record: RemoteAgent) -> RemoteAgent: ...


class TemplateSource(Protocol):
    async def render(self, template_id: str, params: Mapping[str, str]) -> Mapping[str, str]: ...


class ModelProvider(Protocol):
    name: str
    egress: Literal["none", "third_party"]

    async def complete(self, request: ModelRequest) -> ModelResponse: ...


class EmbeddingProvider(Protocol):
    """A provider that can embed texts (ADR-0035); it may also implement ModelProvider."""

    name: str
    egress: Literal["none", "third_party"]

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...


class ModelGateway(Protocol):
    async def complete(
        self, invocation: Invocation, request: ModelRequest, policy: ModelPolicy
    ) -> ModelResponse: ...


class ToolGateway(Protocol):
    async def invoke(
        self, invocation: Invocation, request: ToolRequest, policy: PolicyEngine
    ) -> ToolResponse: ...


__all__ = [
    "AgentLifecycleStore",
    "AgentRegistry",
    "ApprovalGate",
    "AuditSink",
    "ConnectorRequestStore",
    "CredentialStore",
    "EvalReportStore",
    "IdentityProvider",
    "ModelGateway",
    "ModelProvider",
    "PeerGrantStore",
    "PeerStore",
    "PolicyEngine",
    "QuotaManager",
    "RemoteAgentStore",
    "SecretProvider",
    "TemplateSource",
    "ToolGateway",
    "ToolGrantStore",
    "TriggerFireStore",
    "TriggerStore",
]


class ConnectorStore(Protocol):
    async def add(self, spec: Any) -> Any: ...

    async def get(self, connector_id: str) -> Any: ...

    async def list(self, tenant: str) -> builtins.list[Any]: ...

    async def list_all(self) -> builtins.list[Any]: ...

    async def disable(self, connector_id: str, *, by: str) -> Any: ...
