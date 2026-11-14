"""External connector specs and their egress-facing validation (ADR-0013)."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .policy import DataClass

ConnectorKind = Literal["http", "openapi", "mcp"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"
_AUTH_REFERENCE = r"^secret://[A-Za-z0-9._/-]+$"
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_MAX_RESPONSE = 8 * 1024 * 1024


class ConnectorStoreError(Exception):
    """Base class for connector store failures."""


class ConnectorNotFound(ConnectorStoreError):
    """No connector has the given id."""


class ConnectorConflict(ConnectorStoreError):
    """The connector id already exists with a different definition."""


class ConnectorForbidden(ConnectorStoreError):
    """The caller may not read or change the connector."""


class ConnectorStoreUnavailable(ConnectorStoreError):
    """The connector store backend cannot be reached."""


class ConnectorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    connector_id: str = Field(pattern=_SAFE_NAME)
    tenant: str | None = Field(default=None, pattern=_SAFE_NAME)
    kind: ConnectorKind
    base_url: str = Field(min_length=1)
    auth_ref: str | None = Field(default=None, pattern=_AUTH_REFERENCE)
    methods: list[HttpMethod] = Field(min_length=1)
    path_prefixes: list[str] = Field(default_factory=lambda: ["/"], min_length=1)
    data_classes: list[DataClass] = Field(default_factory=list)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_response_bytes: int = Field(default=1024 * 1024, ge=1, le=_MAX_RESPONSE)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def _safe_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.username or parts.password:
            raise ValueError("base_url must not embed credentials; use auth_ref")
        if parts.scheme == "https":
            if not parts.hostname:
                raise ValueError("base_url needs a host")
            return value
        if parts.scheme == "http" and parts.hostname in _LOOPBACK:
            return value
        raise ValueError("base_url must be https, or http only on a loopback host")

    @field_validator("path_prefixes")
    @classmethod
    def _safe_prefixes(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith("/") or "\\" in value or ".." in value.split("/"):
                raise ValueError("path prefixes must start with / and contain no ..")
        return values


__all__ = [
    "ConnectorConflict",
    "ConnectorKind",
    "ConnectorNotFound",
    "ConnectorSpec",
    "ConnectorStoreError",
    "ConnectorStoreUnavailable",
    "HttpMethod",
]
