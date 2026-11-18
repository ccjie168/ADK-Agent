"""Tenant credential reference bindings (SLICE-121 / ADR-0022 decision 5).

Bindings carry metadata only. Secret values stay in the process environment,
addressed by ``secret://<tenant>/<name>``.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$"
_SEGMENT = r"[A-Za-z0-9._-]{1,128}"
_SECRET_REF = re.compile(rf"^secret://({_SEGMENT})/({_SEGMENT})$")


class CredentialStoreError(Exception):
    """Base class for credential store failures."""


class CredentialNotFound(CredentialStoreError):
    """No binding has the given tenant and credential id."""


class CredentialConflict(CredentialStoreError):
    """The binding key already exists with a different definition."""


class CredentialStoreUnavailable(CredentialStoreError):
    """The credential store backend cannot be reached."""


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def credential_version(key_id: str | None) -> str:
    """AgentRef version for credential audit events; always safe for the schema."""
    if not key_id:
        return "credential"
    if _SAFE_VERSION.fullmatch(f"credential.{key_id}"):
        return f"credential.{key_id}"
    return f"credential.{hashlib.sha256(key_id.encode('utf-8')).hexdigest()[:12]}"


def parse_credential_ref(reference: str) -> tuple[str, str]:
    """Split a two-segment ``secret://tenant/name`` reference."""
    match = _SECRET_REF.fullmatch(reference) if isinstance(reference, str) else None
    if match is None:
        raise ValueError(f"invalid credential reference {reference!r}")
    return match.group(1), match.group(2)


def credential_env_name(reference: str) -> str:
    """Map ``secret://<tenant>/<name>`` to ``ADK_SECRET_<TENANT>_<NAME>``."""
    tenant, name = parse_credential_ref(reference)
    mapped = "".join(
        character.upper() if character.isalnum() else "_" for character in f"{tenant}_{name}"
    )
    return "ADK_SECRET_" + mapped


class CredentialBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_id: str = Field(pattern=_SAFE_NAME)
    tenant: str = Field(pattern=_SAFE_NAME)
    secret_ref: str = Field(pattern=rf"^secret://{_SEGMENT}/{_SEGMENT}$")
    description: str = Field(default="", max_length=500)
    created_by: str = Field(min_length=1)
    created_at: datetime
    enabled: bool = True
    wrapped_secret: dict[str, Any] | None = None
    secret_key_id: str | None = None
    secret_version: int | None = Field(default=None, ge=1)

    @field_validator("created_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _ref_tenant_matches(self) -> CredentialBinding:
        tenant, _ = parse_credential_ref(self.secret_ref)
        if tenant != self.tenant:
            raise ValueError("secret_ref tenant must equal tenant")
        return self


__all__ = [
    "CredentialBinding",
    "CredentialConflict",
    "CredentialNotFound",
    "CredentialStoreError",
    "CredentialStoreUnavailable",
    "credential_env_name",
    "credential_version",
    "parse_credential_ref",
]
