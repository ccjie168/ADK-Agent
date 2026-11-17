"""Resolve secret references from the environment or an injected mapping."""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..core import SecretProvider, credential_env_name, parse_credential_ref

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


class TenantSecretProvider:
    """Resolve ``secret://tenant/name`` from stored ciphertext, then the environment."""

    def __init__(self, backend: Any = None, credentials: Any = None) -> None:
        self._backend = backend
        self._credentials = credentials

    async def _stored(self, tenant: str, reference: str) -> str | None:
        if self._credentials is None:
            return None
        bindings = await self._credentials.list(tenant)
        matching = [item for item in bindings if item.secret_ref == reference]
        encrypted = [item for item in matching if item.wrapped_secret is not None]
        if not encrypted:
            return None
        if self._backend is None:
            raise SecretNotFound(f"secret {reference} has ciphertext but no key backend")
        candidates = sorted(
            (item for item in encrypted if item.enabled), key=lambda item: item.credential_id
        )
        if not candidates:
            raise SecretNotFound(f"secret {reference} is disabled")
        binding = candidates[0]
        aad = _credential_aad(binding.tenant, binding.credential_id)
        try:
            return self._backend.unwrap(binding.wrapped_secret, aad).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise SecretNotFound(f"secret {reference} cannot be decrypted") from exc

    async def resolve(self, reference: str) -> str:
        try:
            tenant, name = parse_credential_ref(reference)
        except ValueError:
            raise SecretNotFound(f"invalid secret reference {reference!r}") from None
        stored = await self._stored(tenant, reference)
        if stored is not None:
            return _checked(reference, stored)
        try:
            env_name = credential_env_name(reference)
        except ValueError:
            raise SecretNotFound(f"invalid secret reference {reference!r}") from None
        value = os.environ.get(env_name)
        if value is None:
            raise SecretNotFound(f"secret {reference!r} is not set")
        return _checked(reference, value)


def _credential_aad(tenant: str, credential_id: str) -> bytes:
    return f"adk-credential:{tenant}:{credential_id}".encode()


class TenantScopedSecretProvider:
    """Reject two-segment references owned by another tenant before delegating."""

    def __init__(self, inner: SecretProvider, tenant: str) -> None:
        self._inner = inner
        self._tenant = tenant

    async def resolve(self, reference: str) -> str:
        try:
            tenant, _ = parse_credential_ref(reference)
        except ValueError:
            return await self._inner.resolve(reference)
        if tenant != self._tenant:
            raise SecretNotFound(f"secret {reference!r} belongs to another tenant")
        return await self._inner.resolve(reference)


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


def credential_aad(tenant: str, credential_id: str) -> bytes:
    return _credential_aad(tenant, credential_id)
