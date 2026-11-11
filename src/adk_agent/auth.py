"""Bearer-token auth for HTTP surfaces (MCP and the console)."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
OPEN_PATHS = frozenset({"/healthz"})


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without ``Authorization: Bearer <token>``."""

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        open_paths: frozenset[str] = OPEN_PATHS,
    ) -> None:
        super().__init__(app)
        self.token = token
        self.open_paths = open_paths

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self.open_paths:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        parts = header.split(None, 1)
        valid = (
            len(parts) == 2
            and parts[0].lower() == "bearer"
            and secrets.compare_digest(parts[1], self.token)
        )
        if not valid:
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


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
