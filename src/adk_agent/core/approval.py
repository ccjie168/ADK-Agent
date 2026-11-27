"""Human approval request and decision for a plan step."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .identity import Principal
from .manifest import AgentRef


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    agent_ref: AgentRef
    principal: Principal
    input: str
    reason: str = ""
    requested_at: datetime
    expires_at: datetime | None = None

    @field_validator("requested_at", "expires_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    approved: bool
    approver: str = Field(min_length=1)
    reason: str = ""
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        return value


class ApprovalNotice(BaseModel):
    """A submitted, decided, or expired approval (ADR-0049)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["submitted", "decided", "expired"]
    request_id: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    approved: bool | None = None
    approver: str | None = None
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("expires_at must be timezone-aware")
        return value
