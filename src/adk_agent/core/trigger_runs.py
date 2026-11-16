"""Idempotency records for webhook trigger runs (SLICE-125).

One record per ``(tenant, trigger_id, idempotency_key)``. The record is a state
machine: a run starts ``running`` and ends ``ok``, ``error`` or ``denied``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TriggerFireStatus = Literal["running", "ok", "error", "denied"]

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"
_TRIGGER_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_IDEMPOTENCY_KEY = r"^[A-Za-z0-9._-]{1,128}$"


class TriggerFireError(Exception):
    """Base class for trigger fire record failures."""


class TriggerFireConflict(TriggerFireError):
    """The requested fire record does not exist."""


class TriggerFireStoreUnavailable(TriggerFireError):
    """The fire store backend cannot be reached."""


class TriggerFire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(pattern=_SAFE_NAME)
    trigger_id: str = Field(pattern=_TRIGGER_ID)
    idempotency_key: str = Field(pattern=_IDEMPOTENCY_KEY)
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    status: TriggerFireStatus
    created_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None

    @field_validator("created_at", "finished_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("trigger fire times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _terminal_state(self) -> TriggerFire:
        if self.status == "running" and self.finished_at is not None:
            raise ValueError("running fires cannot have finished_at")
        if self.status != "running" and self.finished_at is None:
            raise ValueError("terminal fires need finished_at")
        return self


__all__ = [
    "TriggerFire",
    "TriggerFireConflict",
    "TriggerFireError",
    "TriggerFireStatus",
    "TriggerFireStoreUnavailable",
]
