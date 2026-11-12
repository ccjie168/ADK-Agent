"""Role-based access policy. Bindings are tenant-scoped and deny by default."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_SAFE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class RoleBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    tenant: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class AccessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    bindings: list[RoleBinding] = Field(default_factory=list)
