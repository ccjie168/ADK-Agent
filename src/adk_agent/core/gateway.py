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
    policy: ModelPolicy
