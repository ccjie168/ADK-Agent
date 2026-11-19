"""Wire contract for a separately deployed model gateway."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .invocation import Invocation
from .manifest import ModelPolicy
from .model import ModelRequest


class ModelGatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation: Invocation
    request: ModelRequest
    # Deprecated: the gateway resolves policy server-side from the registry (ADR-0028).
    # Retained as optional so old callers do not break validation, but it is ignored.
    policy: ModelPolicy | None = None
