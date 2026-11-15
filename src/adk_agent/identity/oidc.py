"""OIDC identity provider backed by PyJWT."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal, TypeGuard
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.identity import Principal

ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
IdentityKind = Literal["human", "service", "agent"]
KINDS: frozenset[str] = frozenset({"human", "service", "agent"})

MALFORMED_CREDENTIAL = "invalid token"
DISALLOWED_ALGORITHM = "algorithm not allowed"
MISSING_KEY_ID = "missing key id"
INVALID_CLAIMS = "invalid claims"
KEY_RESOLUTION_FAILED = "OIDC key resolution failed"
MISSING_DEPENDENCY = 'OIDC needs PyJWT: pip install "adk-agent[oidc]"'


class IdentityError(Exception):
    """Base class for identity resolution failures."""


class InvalidIdentity(IdentityError):
    """The presented credential is not a valid identity."""


class IdentityUnavailable(IdentityError):
    """Identity verification cannot run, for example a missing dependency."""


class OidcBrowserConfig(BaseModel):
    """Settings for the browser PKCE flow. Secrets stay in the environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: str = Field(min_length=1)
    authorization_endpoint: str = Field(min_length=1)
    token_endpoint: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    client_secret_env: str | None = None

    @field_validator("authorization_endpoint", "token_endpoint", "redirect_uri")
    @classmethod
    def _check_url(cls, value: str) -> str:
        parts = urlsplit(value)
        host = parts.hostname
        if not host:
            raise ValueError("endpoint must have a hostname")
        if parts.scheme not in {"http", "https"}:
            raise ValueError("endpoint must use http or https")
        if host not in LOOPBACK_HOSTS and parts.scheme != "https":
            raise ValueError("endpoint must use https outside loopback")
        return value

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not scope for scope in value):
            raise ValueError("scopes must not be empty")
        return value


class OidcConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    jwks_url: str = Field(min_length=1)
    algorithms: tuple[str, ...] = ("RS256", "ES256")
    leeway_seconds: int = Field(default=60, ge=0)
    tenant_claim: str = Field(default="tenant", min_length=1)
    roles_claim: str = Field(default="roles", min_length=1)
    kind_claim: str = Field(default="kind", min_length=1)
    browser: OidcBrowserConfig | None = None

    @field_validator("algorithms")
    @classmethod
    def _check_algorithms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("algorithms must not be empty")
        unsupported = [alg for alg in value if alg not in ASYMMETRIC_ALGORITHMS]
        if unsupported:
            raise ValueError("algorithms must be asymmetric")
        return value

    @field_validator("jwks_url")
    @classmethod
    def _check_jwks_url(cls, value: str) -> str:
        parts = urlsplit(value)
        host = parts.hostname
        if not host:
            raise ValueError("jwks_url must have a hostname")
        if parts.scheme not in {"http", "https"}:
            raise ValueError("jwks_url must use http or https")
        if host not in LOOPBACK_HOSTS and parts.scheme != "https":
            raise ValueError("jwks_url must use https outside loopback")
        return value


def _jwt() -> Any:
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency is present in dev
        raise IdentityUnavailable(MISSING_DEPENDENCY) from exc
    return jwt


def _is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _is_kind(value: object) -> TypeGuard[IdentityKind]:
    return isinstance(value, str) and value in KINDS


def _to_principal(config: OidcConfig, claims: dict[str, Any]) -> Principal:
    subject = claims.get("sub")
    tenant = claims.get(config.tenant_claim)
    if not _is_text(subject) or not _is_text(tenant):
        raise InvalidIdentity(INVALID_CLAIMS)

    roles = claims.get(config.roles_claim, [])
    if not isinstance(roles, list) or not all(_is_text(role) for role in roles):
        raise InvalidIdentity(INVALID_CLAIMS)

    kind = claims.get(config.kind_claim, "human")
    if not _is_kind(kind):
        raise InvalidIdentity(INVALID_CLAIMS)

    return Principal(
        tenant=tenant,
        subject=subject,
        kind=kind,
        roles=list(roles),
        attributes={},
    )


class OidcIdentityProvider:
    def __init__(
        self,
        config: OidcConfig,
        *,
        key_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self._config = config
        if key_resolver is None:
            client = _jwt().PyJWKClient(config.jwks_url, cache_keys=True, lifespan=300)
            self._resolve_key: Callable[[str], Any] = lambda kid: client.get_signing_key(kid).key
        else:
            self._resolve_key = key_resolver

    async def resolve(self, credential: str) -> Principal:
        pyjwt = _jwt()
        kid = self._check_header(pyjwt, credential)
        try:
            key = await asyncio.to_thread(self._resolve_key, kid)
        except Exception as exc:
            raise IdentityUnavailable(KEY_RESOLUTION_FAILED) from exc
        claims = self._decode(pyjwt, credential, key)
        return _to_principal(self._config, claims)

    def _check_header(self, pyjwt: Any, credential: str) -> str:
        try:
            header = pyjwt.get_unverified_header(credential)
        except pyjwt.InvalidTokenError as exc:
            raise InvalidIdentity(MALFORMED_CREDENTIAL) from exc

        if header.get("alg") not in self._config.algorithms:
            raise InvalidIdentity(DISALLOWED_ALGORITHM)

        kid = header.get("kid")
        if not _is_text(kid):
            raise InvalidIdentity(MISSING_KEY_ID)
        return kid

    def _decode(self, pyjwt: Any, credential: str, key: Any) -> dict[str, Any]:
        try:
            claims = pyjwt.decode(
                credential,
                key,
                algorithms=list(self._config.algorithms),
                audience=self._config.audience,
                issuer=self._config.issuer,
                leeway=self._config.leeway_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
        except pyjwt.InvalidTokenError as exc:
            raise InvalidIdentity(MALFORMED_CREDENTIAL) from exc
        if not isinstance(claims, dict):
            raise InvalidIdentity(INVALID_CLAIMS)
        return claims
