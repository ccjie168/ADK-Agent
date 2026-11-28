"""External connector specs and their egress-facing validation (ADR-0013)."""

from __future__ import annotations

from typing import Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .policy import DataClass, RiskLevel

ConnectorKind = Literal["http", "openapi", "mcp"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
DelegationMode = Literal["service", "controlled-service", "obo-later"]

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"
_AUTH_REFERENCE = r"^secret://[A-Za-z0-9._/-]+$"
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_MAX_RESPONSE = 8 * 1024 * 1024
_RISK_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
_DATA_CLASS_ORDER = ("public", "internal", "confidential", "restricted")


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


class ConnectorOperation(BaseModel):
    """One OpenAPI operation the connector exposes as its own tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(pattern=_SAFE_NAME)
    path: str = Field(min_length=1)
    method: HttpMethod
    risk_level: RiskLevel = "L2"
    data_classes: list[DataClass] = Field(default_factory=lambda: [cast("DataClass", "internal")])
    write: bool = False

    @property
    def requires_approval(self) -> bool:
        return self.risk_level in ("L3", "L4")

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        if not value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("operation paths must start with / and contain no ..")
        return value


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
    risk_level: RiskLevel | None = None
    delegation: DelegationMode = "service"
    enabled: bool = True
    operations: list[ConnectorOperation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _operations_belong_to_connector(self) -> ConnectorSpec:
        prefix = self.connector_id + "."
        seen: set[str] = set()
        for operation in self.operations:
            if not operation.tool_id.startswith(prefix):
                raise ValueError(f"operation tool ids must start with {prefix!r}")
            if operation.tool_id in seen:
                raise ValueError(f"duplicate operation tool id {operation.tool_id!r}")
            seen.add(operation.tool_id)
        return self

    def operation_governance(
        self, operation: ConnectorOperation
    ) -> tuple[RiskLevel, list[DataClass]]:
        """The fail-closed risk and data classes for one operation's tool.

        The connector's own declaration is a floor: a hand-registered connector
        cannot lower an operation below its own risk or narrow its classes.
        """
        rank = max(_RISK_ORDER[operation.risk_level], _RISK_ORDER[self.risk_level or "L2"])
        risk = cast("RiskLevel", next(name for name, value in _RISK_ORDER.items() if value == rank))
        classes = sorted({*self.data_classes, *operation.data_classes}, key=_DATA_CLASS_ORDER.index)
        return risk, classes

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
    "ConnectorOperation",
    "ConnectorKind",
    "ConnectorNotFound",
    "ConnectorSpec",
    "ConnectorStoreError",
    "ConnectorStoreUnavailable",
    "DelegationMode",
    "HttpMethod",
]
