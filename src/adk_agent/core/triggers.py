"""Immutable automation triggers pinned to a published agent version (SLICE-124).

A trigger carries only its definition. The execution service (SLICE-125) reads
the stored records; webhook tokens are represented by their SHA-256 hash alone.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TriggerKind = Literal["schedule", "webhook"]

_TRIGGER_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_TOKEN_HASH = r"^[0-9a-f]{64}$"  # nosec B105  # hex regex, not a secret


class TriggerError(Exception):
    """Base class for trigger failures."""


class TriggerNotFound(TriggerError):
    """No trigger has the given tenant and trigger id."""


class TriggerConflict(TriggerError):
    """The trigger key already exists with a different definition."""


class TriggerStoreUnavailable(TriggerError):
    """The trigger store backend cannot be reached."""


def hash_webhook_token(token: str) -> str:
    """Return the SHA-256 hex digest a webhook caller must present."""
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError("webhook token must be at least 16 characters")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AgentTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_id: str = Field(pattern=_TRIGGER_ID)
    tenant: str = Field(pattern=_SAFE_NAME)
    agent_id: str = Field(pattern=_SAFE_NAME)
    version: str = Field(pattern=_SAFE_NAME)
    digest: str = Field(pattern=_DIGEST)
    kind: TriggerKind
    every_seconds: int | None = None
    webhook_token_hash: str | None = Field(default=None, pattern=_TOKEN_HASH)
    input: str = Field(default="", max_length=8000)
    enabled: bool = True
    created_by: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _kind_shape(self) -> AgentTrigger:
        if self.kind == "schedule":
            if self.every_seconds is None or self.every_seconds < 60:
                raise ValueError("schedule triggers need every_seconds >= 60")
            if self.webhook_token_hash is not None:
                raise ValueError("schedule triggers cannot carry a webhook token hash")
            return self
        if self.webhook_token_hash is None:
            raise ValueError("webhook triggers need a webhook token hash")
        if self.every_seconds is not None:
            raise ValueError("webhook triggers cannot carry every_seconds")
        return self


__all__ = [
    "AgentTrigger",
    "TriggerConflict",
    "TriggerError",
    "TriggerKind",
    "TriggerNotFound",
    "TriggerStoreUnavailable",
    "hash_webhook_token",
]
