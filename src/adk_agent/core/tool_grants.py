"""Tool grant requests and their expiry semantics (ADR-0011)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .policy import DataClass

GrantStatus = Literal["pending", "approved", "denied", "expired", "cancelled"]

_REQUEST_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class GrantStoreError(Exception):
    """Base class for tool grant store failures."""


class GrantRequestError(GrantStoreError):
    """A grant request operation is not allowed."""


class GrantRequestNotFound(GrantRequestError):
    """No grant request has the given id."""


class GrantRequestConflict(GrantRequestError):
    """The grant request already exists or is in a terminal state."""


class GrantRequestExpired(GrantRequestError):
    """The grant request is past its expiry and can no longer change."""


class GrantStoreUnavailable(GrantStoreError):
    """The grant store backend could not be reached."""


class ToolGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    tenant: str = Field(pattern=_SAFE_NAME)
    agent_id: str = Field(pattern=_SAFE_NAME)
    version: str = Field(pattern=_SAFE_NAME)
    digest: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    data_classes: list[DataClass] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    status: GrantStatus = "pending"
    requested_by: str = Field(min_length=1)
    requested_at: datetime
    expires_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str = ""

    @field_validator("requested_at", "expires_at", "decided_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _expiry_after_request(self) -> ToolGrantRequest:
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be later than requested_at")
        return self


def effective_status(request: ToolGrantRequest, now: datetime) -> GrantStatus:
    """Return ``expired`` once a pending or approved request reaches its expiry."""
    if request.status in ("pending", "approved") and now >= request.expires_at:
        return "expired"
    return request.status


def is_active(request: ToolGrantRequest, now: datetime) -> bool:
    return effective_status(request, now) == "approved"


__all__ = [
    "GrantRequestConflict",
    "GrantRequestError",
    "GrantRequestExpired",
    "GrantRequestNotFound",
    "GrantStatus",
    "GrantStoreError",
    "GrantStoreUnavailable",
    "ToolGrantRequest",
    "effective_status",
    "is_active",
]
