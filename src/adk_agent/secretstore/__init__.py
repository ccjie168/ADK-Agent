"""Secret providers and request-time header injection."""

from __future__ import annotations

from .keys import (
    KeyBackend,
    KeyBackendError,
    LocalKeyBackend,
    VaultKeyBackend,
    load_key_backend,
    load_local_backend,
)
from .model_keys import ModelKeyResolver, ModelKeyUnavailable, model_key_aad
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
    "ModelKeyResolver",
    "ModelKeyUnavailable",
    "PrefixedEnvSecretProvider",
    "RoutingSecretProvider",
    "SecretNotFound",
    "TenantScopedSecretProvider",
    "VaultKeyBackend",
    "credential_aad",
    "TenantSecretProvider",
    "load_key_backend",
    "load_local_backend",
    "model_key_aad",
    "secret_header_provider",
]
