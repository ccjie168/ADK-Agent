"""Canary split between a stable and a candidate agent version."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SAFE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class CanaryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    agent_id: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    stable_version: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    canary_version: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    weight: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _versions_differ(self) -> CanaryPolicy:
        if self.weight > 0 and self.stable_version == self.canary_version:
            raise ValueError("a positive canary weight needs two different versions")
        return self
