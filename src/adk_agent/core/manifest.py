"""Agent manifest and the version anchor used at runtime."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .artifact import AgentArtifact
from .policy import DataClass, ToolGrant

Exposure = Literal["none", "mcp", "http", "a2a"]
ExecutionTier = Literal["in_process", "sandboxed"]
RagOnError = Literal["deny", "degrade"]

_SAFE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class ModelCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    allowed_data_classes: list[DataClass] = Field(default_factory=list)


class ModelAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str = Field(pattern=_SAFE_NAME_PATTERN)
    candidates: list[ModelCandidate] = Field(min_length=1)


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_allowlist: list[str] = Field(min_length=1)
    model_allowlist: list[str] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, gt=0)
    budget_usd: float | None = Field(default=None, ge=0)
    model_aliases: list[ModelAlias] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_aliases(self) -> ModelPolicy:
        names = [entry.alias for entry in self.model_aliases]
        if len(set(names)) != len(names):
            raise ValueError("model_aliases must have unique alias names")
        return self


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    pass_threshold: float = Field(ge=0, le=1)


class Slo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_latency_ms: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class RagConfig(BaseModel):
    """Retrieval settings an agent opts into (ADR-0036)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    top_k: int = Field(default=5, ge=1, le=50)
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    data_classes: list[DataClass] = Field(default_factory=list)
    on_error: RagOnError = "deny"


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    version: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    tenant: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    owner: str = Field(min_length=1)
    description: str = ""
    model_policy: ModelPolicy
    tool_grants: list[ToolGrant] = Field(default_factory=list)
    data_scopes: list[DataClass] = Field(default_factory=list)
    exposure: Exposure = "none"
    eval_suite: EvalSuite | None = None
    slo: Slo | None = None
    # None only appears on records published before ADR-0024; it reads as in_process.
    execution_tier: ExecutionTier | None = None
    # Alias the agent's business code references instead of a provider model name (ADR-0033).
    model_alias: str | None = Field(default=None, pattern=_SAFE_NAME_PATTERN)
    # Retrieval is off unless the manifest opts in (ADR-0036).
    rag: RagConfig | None = None


class AgentRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    version: str = Field(min_length=1, pattern=_SAFE_NAME_PATTERN)
    digest: str = Field(min_length=1)
    artifact_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class PublishedAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: AgentManifest
    digest: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    published_at: datetime
    artifact: AgentArtifact | None = None

    @field_validator("published_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        return value


def manifest_digest(manifest: AgentManifest) -> str:
    """Hash the manifest's canonical JSON. The digest is not part of the manifest.

    Fields added after a record was published are dropped while at their default,
    so an unchanged manifest keeps its digest (ADR-0024 execution_tier, ADR-0033
    model_alias/model_aliases).
    """
    payload = manifest.model_dump(mode="json")
    if payload.get("execution_tier") is None:
        payload.pop("execution_tier", None)
    if payload.get("model_alias") is None:
        payload.pop("model_alias", None)
    if payload.get("rag") is None:
        payload.pop("rag", None)
    policy = payload.get("model_policy")
    if isinstance(policy, dict) and not policy.get("model_aliases"):
        policy.pop("model_aliases", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def declared_execution_tier(data: Mapping[str, Any]) -> ExecutionTier:
    """Read the tier a new publish must declare; legacy records may omit it."""
    value = data.get("execution_tier")
    if value is None:
        raise ValueError("manifest must declare execution_tier")
    if value not in ("in_process", "sandboxed"):
        raise ValueError("manifest execution_tier must be in_process or sandboxed")
    return cast(ExecutionTier, value)
