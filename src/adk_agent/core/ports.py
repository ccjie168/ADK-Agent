"""Ports the adapters implement. Core depends on these, never on adapters."""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol

from .approval import ApprovalDecision, ApprovalRequest
from .audit import AuditEvent
from .eval import EvalReport
from .identity import Principal
from .invocation import Invocation
from .manifest import AgentRef, ModelPolicy, PublishedAgent
from .model import ModelRequest, ModelResponse
from .policy import PolicyDecision
from .quota import QuotaPolicy
from .tool import ToolRequest, ToolResponse


class AgentRegistry(Protocol):
    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None: ...

    async def publish(self, agent: PublishedAgent) -> PublishedAgent: ...

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]: ...

    async def tenants(self) -> builtins.list[str]: ...


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


class TemplateSource(Protocol):
    async def render(self, template_id: str, params: Mapping[str, str]) -> Mapping[str, str]: ...


class ModelProvider(Protocol):
    name: str
    egress: Literal["none", "third_party"]

    async def complete(self, request: ModelRequest) -> ModelResponse: ...


class ModelGateway(Protocol):
    async def complete(
        self, invocation: Invocation, request: ModelRequest, policy: ModelPolicy
    ) -> ModelResponse: ...


class ToolGateway(Protocol):
    async def invoke(
        self, invocation: Invocation, request: ToolRequest, policy: PolicyEngine
    ) -> ToolResponse: ...


__all__ = [
    "AgentRegistry",
    "ApprovalGate",
    "AuditSink",
    "EvalReportStore",
    "IdentityProvider",
    "ModelGateway",
    "ModelProvider",
    "PolicyEngine",
    "QuotaManager",
    "SecretProvider",
    "TemplateSource",
    "ToolGateway",
]
