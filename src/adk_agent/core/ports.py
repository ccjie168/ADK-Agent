"""Ports the adapters implement. Core depends on these, never on adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

from .audit import AuditEvent
from .identity import Principal
from .invocation import Invocation
from .manifest import AgentRef, ModelPolicy, PublishedAgent
from .model import ModelRequest, ModelResponse
from .policy import PolicyDecision
from .tool import ToolRequest, ToolResponse


class AgentRegistry(Protocol):
    async def get(self, ref: AgentRef) -> PublishedAgent | None: ...

    async def publish(self, agent: PublishedAgent) -> None: ...


class IdentityProvider(Protocol):
    async def resolve(self, credential: str) -> Principal: ...


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
    "AuditSink",
    "IdentityProvider",
    "ModelGateway",
    "ModelProvider",
    "PolicyEngine",
    "SecretProvider",
    "TemplateSource",
    "ToolGateway",
]
