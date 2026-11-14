"""Peer identities and per-agent action grants (ADR-0014)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PeerAction = Literal["read", "invoke"]

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class PeerStoreError(Exception):
    """Base class for peer store failures."""


class PeerStoreUnavailable(PeerStoreError):
    """The peer store backend could not be reached."""


class PeerIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    peer_id: str = Field(pattern=_SAFE_NAME)
    tenant: str = Field(pattern=_SAFE_NAME)
    subject: str = Field(min_length=1)
    kind: Literal["human", "service", "agent"] = "service"
    roles: list[str] = Field(default_factory=list)
    enabled: bool = True


class PeerGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    peer_id: str = Field(pattern=_SAFE_NAME)
    tenant: str = Field(pattern=_SAFE_NAME)
    agent_id: str = Field(pattern=_SAFE_NAME)
    actions: list[PeerAction] = Field(min_length=1)

    @field_validator("actions")
    @classmethod
    def _no_duplicate_actions(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("actions must not contain duplicates")
        return value


__all__ = [
    "PeerAction",
    "PeerGrant",
    "PeerIdentity",
    "PeerStoreError",
    "PeerStoreUnavailable",
]
