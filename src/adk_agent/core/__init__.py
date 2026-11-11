"""Domain contracts. No adapters, no I/O."""

from __future__ import annotations

from .audit import AuditEvent
from .identity import Principal
from .invocation import Invocation
from .manifest import (
    AgentManifest,
    AgentRef,
    EvalSuite,
    ModelPolicy,
    PublishedAgent,
    Slo,
    manifest_digest,
)
from .model import Message, ModelRequest, ModelResponse
from .policy import DataClass, PolicyDecision, ToolGrant
from .ports import (
    AgentRegistry,
    AuditSink,
    IdentityProvider,
    ModelGateway,
    ModelProvider,
    PolicyEngine,
    SecretProvider,
    TemplateSource,
)

__all__ = [
    "AgentManifest",
    "AgentRef",
    "AgentRegistry",
    "AuditEvent",
    "AuditSink",
    "DataClass",
    "EvalSuite",
    "IdentityProvider",
    "Invocation",
    "Message",
    "ModelGateway",
    "ModelPolicy",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "PolicyDecision",
    "PolicyEngine",
    "Principal",
    "PublishedAgent",
    "SecretProvider",
    "Slo",
    "TemplateSource",
    "ToolGrant",
    "manifest_digest",
]
