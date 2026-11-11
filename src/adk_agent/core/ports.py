"""Ports the adapters implement. Core depends on these, never on adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .audit import AuditEvent
from .identity import Principal
from .invocation import Invocation
from .manifest import AgentRef, PublishedAgent
from .policy import PolicyDecision


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


__all__ = [
    "AgentRegistry",
    "AuditSink",
    "IdentityProvider",
    "PolicyEngine",
    "SecretProvider",
    "TemplateSource",
]
