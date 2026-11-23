"""Role definitions: a role is a named capability set (ADR-0041 phase 1).

The capability vocabulary is the console panel permission names. Role
definitions are global (not tenant-scoped); user-to-role bindings, which are
tenant-scoped, arrive in a later slice.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SAFE_CAPABILITY = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")

CAPABILITIES_ALL = frozenset(
    {
        "chat.run",
        "runs.read",
        "sessions.read",
        "approvals.read",
        "approvals.decide",
        "grants.read",
        "grants.request",
        "grants.decide",
        "audit.read",
        "registry.read",
        "registry.publish",
        "registry.load",
        "eval.read",
        "tools.read",
        "lifecycle.read",
        "connectors.read",
        "connectors.manage",
        "peers.read",
        "peers.manage",
        "policy.read",
        "policy.write",
        "model.read",
        "model.write",
        "semantics.write",
        "ops.read",
        "ops.status",
        "roles.read",
        "roles.manage",
    }
)
CAPABILITIES_BASE = frozenset({"chat.run", "runs.read", "sessions.read"})
CAPABILITIES_OPERATOR = CAPABILITIES_BASE | {
    "approvals.read",
    "approvals.decide",
    "grants.read",
    "audit.read",
    "connectors.read",
    "peers.read",
    "registry.read",
    "policy.read",
    "model.read",
    "semantics.write",
    "ops.read",
}
CAPABILITIES_PUBLISHER = CAPABILITIES_BASE | {
    "registry.read",
    "registry.publish",
    "registry.load",
    "eval.read",
    "tools.read",
    "lifecycle.read",
    "grants.read",
    "grants.request",
}


class RoleStoreError(Exception):
    """Base class for role definition store failures."""


class RoleNotFound(RoleStoreError):
    """No role has the given name."""


class RoleConflict(RoleStoreError):
    """The role name already exists with a different definition."""


class RoleStoreUnavailable(RoleStoreError):
    """The role store backend cannot be reached."""


class RoleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=_SAFE_NAME.pattern)
    capabilities: tuple[str, ...] = Field(default=())
    builtin: bool = False
    description: str = Field(default="", max_length=500)

    @field_validator("capabilities")
    @classmethod
    def _normalize_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for capability in value:
            if not _SAFE_CAPABILITY.fullmatch(capability):
                raise ValueError(f"invalid capability name {capability!r}")
            if capability not in normalized:
                normalized.append(capability)
        return tuple(sorted(normalized))


# Built-in role seeds. `base` is the fallback capability floor, kept as a role
# so the admin UI can show it; the runtime fallback never reads it from the store.
BUILTIN_ROLES: dict[str, frozenset[str]] = {
    "admin": CAPABILITIES_ALL,
    "operator": CAPABILITIES_OPERATOR,
    "ops": CAPABILITIES_OPERATOR,
    "approver": CAPABILITIES_OPERATOR,
    "publisher": CAPABILITIES_PUBLISHER,
    "developer": CAPABILITIES_PUBLISHER,
    "base": CAPABILITIES_BASE,
}


def seed_builtin_roles() -> list[RoleDefinition]:
    """Return the built-in roles as store-ready definitions (backward compatible)."""
    return [
        RoleDefinition(name=name, capabilities=tuple(sorted(capabilities)), builtin=True)
        for name, capabilities in BUILTIN_ROLES.items()
    ]


__all__ = [
    "BUILTIN_ROLES",
    "CAPABILITIES_ALL",
    "CAPABILITIES_BASE",
    "CAPABILITIES_OPERATOR",
    "CAPABILITIES_PUBLISHER",
    "RoleConflict",
    "RoleDefinition",
    "RoleNotFound",
    "RoleStoreError",
    "RoleStoreUnavailable",
    "seed_builtin_roles",
]
