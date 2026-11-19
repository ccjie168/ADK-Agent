"""Idempotency records for write-tool calls (ADR-0034).

One record per ``(tenant, tool_id, idempotency_key)``. A call is ``claimed``
before execution and ends ``completed`` (result known) or ``unknown`` (executed
but the result could not be serialized).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .policy import DataClass

ToolExecutionStatus = Literal["claimed", "completed", "unknown"]

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class ToolIdempotencyError(Exception):
    """Base class for tool idempotency record failures."""


class ToolIdempotencyConflict(ToolIdempotencyError):
    """The requested execution record does not exist."""


class ToolIdempotencyUnavailable(ToolIdempotencyError):
    """The idempotency store backend cannot be reached."""


class ToolExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(pattern=_SAFE_NAME)
    tool_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    status: ToolExecutionStatus = "claimed"
    output: Any = None
    data_classes: list[DataClass] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    expires_at: datetime
    finished_at: datetime | None = None

    @field_validator("created_at", "expires_at", "finished_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("tool execution times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _valid_lifecycle(self) -> ToolExecutionRecord:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.status == "claimed" and self.finished_at is not None:
            raise ValueError("claimed records cannot have finished_at")
        if self.status != "claimed" and self.finished_at is None:
            raise ValueError("terminal records need finished_at")
        return self


__all__ = [
    "ToolExecutionRecord",
    "ToolExecutionStatus",
    "ToolIdempotencyConflict",
    "ToolIdempotencyError",
    "ToolIdempotencyUnavailable",
]
