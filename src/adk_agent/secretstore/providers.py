"""Resolve secret references from the environment or an injected mapping."""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..core import SecretProvider

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")


class SecretNotFound(Exception):
    """The secret reference cannot be resolved."""


def _checked(reference: str, value: str) -> str:
    if not value:
        raise SecretNotFound(f"secret {reference!r} is empty")
    if "\r" in value or "\n" in value:
        raise SecretNotFound(f"secret {reference!r} contains a newline")
    return value


def _env_name(reference: str) -> str:
    if not _ENV_NAME.fullmatch(reference):
        raise SecretNotFound(f"invalid secret reference {reference!r}")
    return reference


class EnvSecretProvider:
    """Read secrets from environment variables named by the reference."""

    async def resolve(self, reference: str) -> str:
        value = os.environ.get(_env_name(reference))
        if value is None:
            raise SecretNotFound(f"secret {reference!r} is not set")
        return _checked(reference, value)


class PrefixedEnvSecretProvider:
    """Map ``secret://a/b`` to ``<prefix>A_B`` in the environment."""

    def __init__(self, prefix: str = "ADK_SECRET_") -> None:
        self._prefix = prefix

    def _env_name(self, reference: str) -> str:
        if not reference.startswith("secret://"):
            raise SecretNotFound(f"invalid secret reference {reference!r}")
        suffix = reference[len("secret://") :]
        name = "".join(character.upper() if character.isalnum() else "_" for character in suffix)
        return _env_name(self._prefix + name)

    async def resolve(self, reference: str) -> str:
        name = self._env_name(reference)
        value = os.environ.get(name)
        if value is None:
            raise SecretNotFound(f"secret {reference!r} is not set")
        return _checked(reference, value)


class MappingSecretProvider:
    """Read secrets from an in-memory mapping, for tests and injected config."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    async def resolve(self, reference: str) -> str:
        value = self._values.get(reference)
        if value is None:
            raise SecretNotFound(f"secret {reference!r} is not set")
        return _checked(reference, value)


def secret_header_provider(
    secrets: SecretProvider, header_refs: Mapping[str, str]
) -> Callable[[Any], Awaitable[dict[str, str]]]:
    """Build a request-time header provider from header -> secret-reference pairs."""
    for header in header_refs:
        if not _HEADER_NAME.fullmatch(header):
            raise ValueError(f"invalid header name {header!r}")

    async def provide(_context: Any) -> dict[str, str]:
        return {header: await secrets.resolve(ref) for header, ref in header_refs.items()}

    return provide
