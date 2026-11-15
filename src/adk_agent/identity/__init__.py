"""Identity adapters."""

from __future__ import annotations

from .oidc import (
    IdentityError,
    IdentityUnavailable,
    InvalidIdentity,
    OidcBrowserConfig,
    OidcConfig,
    OidcIdentityProvider,
)
from .oidc_login import OidcLogin, OidcLoginError

__all__ = [
    "IdentityError",
    "IdentityUnavailable",
    "InvalidIdentity",
    "OidcBrowserConfig",
    "OidcConfig",
    "OidcIdentityProvider",
    "OidcLogin",
    "OidcLoginError",
]
