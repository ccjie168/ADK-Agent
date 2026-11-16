"""Tenant connector registration requests and their pending/terminal states (SLICE-122)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .connectors import ConnectorSpec

ConnectorRequestStatus = Literal["pending", "approved", "denied"]

_REQUEST_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"


class ConnectorRequestError(Exception):
    """Base class for connector request failures."""


class ConnectorRequestNotFound(ConnectorRequestError):
    """No connector request has the given id."""


class ConnectorRequestConflict(ConnectorRequestError):
    """The connector request already exists or is no longer pending."""


class ConnectorRequestStoreUnavailable(ConnectorRequestError):
    """The connector request store backend could not be reached."""


class ConnectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    tenant: str = Field(pattern=_SAFE_NAME)
    spec: ConnectorSpec
    reason: str = Field(min_length=1, max_length=2000)
    status: ConnectorRequestStatus = "pending"
    requested_by: str = Field(min_length=1)
    requested_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str = ""
    registered_connector: str | None = None

    @field_validator("requested_at", "decided_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _consistent_decision(self) -> ConnectorRequest:
        if self.spec.tenant != self.tenant:
            raise ValueError("spec tenant must equal request tenant")
        if self.status == "pending":
            if (
                self.decided_by is not None
                or self.decided_at is not None
                or self.registered_connector is not None
            ):
                raise ValueError("pending requests cannot carry decision fields")
            return self
        if self.decided_by is None or self.decided_at is None:
            raise ValueError("decided requests need decided_by and decided_at")
        if self.status == "approved":
            if self.registered_connector is None:
                raise ValueError("approved requests need a registered connector")
        elif self.registered_connector is not None:
            raise ValueError("denied requests cannot register a connector")
        return self


__all__ = [
    "ConnectorRequest",
    "ConnectorRequestConflict",
    "ConnectorRequestError",
    "ConnectorRequestNotFound",
    "ConnectorRequestStatus",
    "ConnectorRequestStoreUnavailable",
]
