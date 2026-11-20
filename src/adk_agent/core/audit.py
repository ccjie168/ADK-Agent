"""Append-only audit event. One state transition, one record."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .identity import Principal
from .manifest import AgentRef
from .policy import DataClass, RiskLevel


def _is_none(value: object) -> bool:
    return value is None


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    principal: Principal
    approver: str | None = None
    agent_ref: AgentRef
    action: str = Field(min_length=1)
    target: str = Field(min_length=1)
    args_hash: str | None = None
    result_hash: str | None = None
    policy_decision_id: str | None = None
    policy_version: str | None = None
    data_classes: list[DataClass] = Field(default_factory=list)
    latency_ms: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    egress: Literal["none", "third_party"] = "none"
    status: Literal["ok", "error", "denied"]
    error_code: str | None = None
    risk_level: RiskLevel | None = None
    model_alias: str | None = None
    fallback_count: int = Field(default=0, ge=0)
    # Omitted while unused to keep payloads small; chain hashes no longer depend on
    # field presence, they hash the stored event JSON (ADR-0037).
    rag_top_k: int | None = Field(default=None, ge=0, exclude_if=_is_none)
    rag_returned: int | None = Field(default=None, ge=0, exclude_if=_is_none)
    rag_filtered: int | None = Field(default=None, ge=0, exclude_if=_is_none)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _tenant_matches_principal(self) -> AuditEvent:
        if self.tenant != self.principal.tenant:
            raise ValueError("tenant must equal principal.tenant")
        return self


class AuditRecord(BaseModel):
    """One link in a tenant's audit hash chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: AuditEvent
    prev_hash: str = Field(pattern=r"^([0-9a-f]{64})?$")
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    kid: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
