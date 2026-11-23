"""Tenant-scoped user-to-role bindings (ADR-0041 phase 1).

A binding maps a ``(tenant, subject)`` to a set of role names. Roles must be
well-formed role names (the same whitelist as ``RoleDefinition.name``), but the
binding store does not check that each role is defined in the role store; that
cross-store validation belongs to the runtime-resolution slice.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SAFE_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SAFE_ROLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


class UserBindingStoreError(Exception):
    """Base class for user binding store failures."""


class UserBindingNotFound(UserBindingStoreError):
    """No binding has the given tenant and subject."""


class UserBindingConflict(UserBindingStoreError):
    """The (tenant, subject) key already exists with a different role set."""


class UserBindingStoreUnavailable(UserBindingStoreError):
    """The user binding store backend cannot be reached."""


class UserBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(pattern=_SAFE_TENANT.pattern)
    subject: str = Field(min_length=1, max_length=256)
    roles: tuple[str, ...] = Field(default=())

    @field_validator("roles")
    @classmethod
    def _normalize_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for role in value:
            if not _SAFE_ROLE.fullmatch(role):
                raise ValueError(f"invalid role name {role!r}")
            if role not in normalized:
                normalized.append(role)
        return tuple(sorted(normalized))


__all__ = [
    "UserBinding",
    "UserBindingConflict",
    "UserBindingNotFound",
    "UserBindingStoreError",
    "UserBindingStoreUnavailable",
]
