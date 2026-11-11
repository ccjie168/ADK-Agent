"""Policy domain types shared by manifests and audit events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DataClass = Literal["public", "internal", "confidential", "restricted"]


class ToolGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(min_length=1)
    data_classes: list[DataClass] = Field(default_factory=list)
    requires_approval: bool = False


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["allow", "deny"]
    reason: str = Field(min_length=1)
    obligations: list[str] = Field(default_factory=list)
    policy_version: str = Field(min_length=1)
