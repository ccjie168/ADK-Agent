"""Sandbox limits and the HTTP tool-source egress allowlist."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import SandboxViolation

_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float = Field(default=10.0, gt=0, le=600)
    max_cpu_seconds: int | None = Field(default=None, gt=0, le=600)
    max_memory_mb: int | None = Field(default=None, gt=0)
    allow_network: bool = False
    allowed_hosts: list[str] | None = None
    env_allowlist: list[str] = Field(default_factory=list)

    @field_validator("allowed_hosts")
    @classmethod
    def _normalize_hosts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        hosts: list[str] = []
        for host in value:
            candidate = host.strip().lower()
            if not _HOST.fullmatch(candidate):
                raise ValueError(f"invalid host {host!r}")
            hosts.append(candidate)
        return hosts

    @field_validator("env_allowlist")
    @classmethod
    def _valid_env_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if not _ENV_NAME.fullmatch(name):
                raise ValueError(f"invalid environment variable name {name!r}")
        return value


def check_url(url: str, policy: SandboxPolicy) -> None:
    """Deny a tool-source URL whose host is outside the allowlist."""
    if policy.allowed_hosts is None:
        return
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        raise SandboxViolation(f"tool URL has no host: {url!r}")
    if host not in policy.allowed_hosts:
        raise SandboxViolation(f"tool host {host!r} is not allowed")
