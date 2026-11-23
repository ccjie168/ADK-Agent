"""Bearer-token auth for HTTP surfaces (MCP and the console)."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .core import IdentityProvider, Principal
from .identity import IdentityUnavailable, InvalidIdentity

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
OPEN_PATHS = frozenset({"/healthz"})


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _is_open(path: str, open_paths: frozenset[str], open_prefixes: frozenset[str]) -> bool:
    """True when ``path`` needs no auth, either an exact match or under an open prefix."""
    return path in open_paths or any(path.startswith(prefix) for prefix in open_prefixes)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without ``Authorization: Bearer <token>``."""

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        open_paths: frozenset[str] = OPEN_PATHS,
        open_prefixes: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(app)
        self.token = token
        self.open_paths = open_paths
        self.open_prefixes = open_prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_open(request.url.path, self.open_paths, self.open_prefixes):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        parts = header.split(None, 1)
        valid = (
            len(parts) == 2
            and parts[0].lower() == "bearer"
            and secrets.compare_digest(parts[1], self.token)
        )
        if not valid:
            return _unauthorized()
        return await call_next(request)


class OidcAuthMiddleware(BaseHTTPMiddleware):
    """Resolve ``Authorization: Bearer <jwt>`` into ``request.state.principal``."""

    def __init__(
        self,
        app: ASGIApp,
        provider: IdentityProvider,
        open_paths: frozenset[str] = OPEN_PATHS,
        open_prefixes: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(app)
        self.provider = provider
        self.open_paths = open_paths
        self.open_prefixes = open_prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_open(request.url.path, self.open_paths, self.open_prefixes):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return _unauthorized()
        try:
            principal = await self.provider.resolve(parts[1])
        except InvalidIdentity:
            return _unauthorized()
        except IdentityUnavailable:
            return JSONResponse({"error": "identity_unavailable"}, status_code=503)
        request.state.principal = principal
        return await call_next(request)


def bind_principal(request: Request, claimed: Principal) -> Principal | None:
    """Return the token principal when it matches the caller's claim, else ``None``."""
    verified = getattr(request.state, "principal", None)
    if verified is None:
        return claimed
    if claimed.tenant != verified.tenant or claimed.subject != verified.subject:
        return None
    return verified


def resolve_http_auth(
    host: str,
    auth_token: str | None,
    allow_unauthenticated: bool,
) -> str | None:
    """Return the token to enforce, or raise before serving an unsafe endpoint."""
    if auth_token:
        return auth_token
    if allow_unauthenticated:
        if host not in LOOPBACK_HOSTS:
            raise ValueError(
                "allow_unauthenticated is only allowed on a loopback host "
                f"(got {host!r}); pass auth_token for a network bind"
            )
        return None
    raise ValueError(
        "refusing to serve MCP over HTTP without auth (CP-S6): pass auth_token, "
        "or allow_unauthenticated=True on a loopback host"
    )
