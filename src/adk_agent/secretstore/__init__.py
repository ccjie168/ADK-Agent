"""Secret providers and request-time header injection."""

from __future__ import annotations

from .keys import KeyBackend, KeyBackendError, LocalKeyBackend, VaultKeyBackend, load_key_backend
from .providers import (
    EnvSecretProvider,
    MappingSecretProvider,
    PrefixedEnvSecretProvider,
    RoutingSecretProvider,
    SecretNotFound,
    TenantScopedSecretProvider,
    TenantSecretProvider,
    credential_aad,
    secret_header_provider,
)

__all__ = [
    "EnvSecretProvider",
    "KeyBackend",
    "KeyBackendError",
    "LocalKeyBackend",
    "MappingSecretProvider",
    "PrefixedEnvSecretProvider",
    "RoutingSecretProvider",
    "SecretNotFound",
    "TenantScopedSecretProvider",
    "VaultKeyBackend",
    "credential_aad",
    "TenantSecretProvider",
    "load_key_backend",
    "secret_header_provider",
]
