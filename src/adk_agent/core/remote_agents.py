"""Remote A2A agent catalog records (ADR-0015)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

RemoteAgentStatus = Literal["pinned", "changed", "unreachable"]
RemoteAgentFetchReason = Literal["unreachable", "unauthorized", "too_large", "invalid_card"]

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"
_CREDENTIAL_REF = r"^secret://[A-Za-z0-9._/-]+$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


class RemoteAgentError(Exception):
    """Base class for remote agent failures."""


class RemoteAgentStoreUnavailable(RemoteAgentError):
    """A remote agent store read or write failed."""


class RemoteAgentFetchError(RemoteAgentError):
    """A remote agent card could not be fetched or parsed."""

    reason: RemoteAgentFetchReason

    def __init__(self, reason: RemoteAgentFetchReason) -> None:
        super().__init__(reason)
        self.reason = reason


def _safe_card_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise ValueError("agent_card_url must not embed credentials")
    if parts.scheme == "https":
        if not parts.hostname:
            raise ValueError("agent_card_url needs a host")
        return value
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return value
    raise ValueError("agent_card_url must be https, or http only on a loopback host")


class RemoteAgentRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    remote_id: str = Field(pattern=_SAFE_NAME)
    tenant: str = Field(pattern=_SAFE_NAME)
    peer_id: str = Field(pattern=_SAFE_NAME)
    agent_card_url: str = Field(min_length=1)
    credential_ref: str | None = Field(default=None, pattern=_CREDENTIAL_REF)
    label: str = ""

    @field_validator("agent_card_url")
    @classmethod
    def _validate_card_url(cls, value: str) -> str:
        return _safe_card_url(value)


class RemoteAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    remote_id: str = Field(pattern=_SAFE_NAME)
    tenant: str = Field(pattern=_SAFE_NAME)
    peer_id: str = Field(pattern=_SAFE_NAME)
    agent_card_url: str = Field(min_length=1)
    credential_ref: str | None = Field(default=None, pattern=_CREDENTIAL_REF)
    label: str = ""
    card_digest: str = Field(pattern=_DIGEST)
    observed_digest: str | None = Field(default=None, pattern=_DIGEST)
    checked_at: datetime
    status: RemoteAgentStatus
    enabled: bool = True

    @field_validator("agent_card_url")
    @classmethod
    def _validate_card_url(cls, value: str) -> str:
        return _safe_card_url(value)

    @field_validator("checked_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value


__all__ = [
    "RemoteAgent",
    "RemoteAgentError",
    "RemoteAgentFetchError",
    "RemoteAgentFetchReason",
    "RemoteAgentRegistration",
    "RemoteAgentStatus",
    "RemoteAgentStoreUnavailable",
]
