"""Agent manifest and the version anchor used at runtime."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .policy import DataClass, ToolGrant

Exposure = Literal["none", "mcp", "http", "a2a"]


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_allowlist: list[str] = Field(min_length=1)
    model_allowlist: list[str] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, gt=0)
    budget_usd: float | None = Field(default=None, ge=0)


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    pass_threshold: float = Field(ge=0, le=1)


class Slo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_latency_ms: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    description: str = ""
    model_policy: ModelPolicy
    tool_grants: list[ToolGrant] = Field(default_factory=list)
    data_scopes: list[DataClass] = Field(default_factory=list)
    exposure: Exposure = "none"
    eval_suite: EvalSuite | None = None
    slo: Slo | None = None


class AgentRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    digest: str = Field(min_length=1)


class PublishedAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: AgentManifest
    digest: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    published_at: datetime

    @field_validator("published_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        return value


def manifest_digest(manifest: AgentManifest) -> str:
    """Hash the manifest's canonical JSON. The digest is not part of the manifest."""
    payload = manifest.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
