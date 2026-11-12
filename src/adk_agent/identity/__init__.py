"""Identity adapters."""

from __future__ import annotations

from .oidc import (
    IdentityError,
    IdentityUnavailable,
    InvalidIdentity,
    OidcConfig,
    OidcIdentityProvider,
)

__all__ = [
    "IdentityError",
    "IdentityUnavailable",
    "InvalidIdentity",
    "OidcConfig",
    "OidcIdentityProvider",
]
