"""HTTP transport for MCP servers, with mandatory bearer-token auth (CP-S6).

Policy (see CLAUDE.md / ADR-0001): an MCP HTTP endpoint must declare auth.
Serving without a token is only allowed on a loopback host, and only when the
caller opts in explicitly with ``allow_unauthenticated=True``.
"""

from __future__ import annotations

import os
from typing import Any

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
        valid = len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == self.token
        if not valid:
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


def resolve_port(port: int | None, default: int = 8000) -> int:
    """Resolve the port: explicit value > ``PORT`` env var (Cloud Run) > default."""
    if port is not None:
        return port
    raw = os.environ.get("PORT")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"PORT must be an integer, got {raw!r}") from exc


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


def build_http_app(
    server: Any,
    *,
    auth_token: str | None,
    host: str = "127.0.0.1",
    allow_unauthenticated: bool = False,
    **kwargs: Any,
) -> Any:
    """Build the streamable-http ASGI app, wrapping it in bearer auth if set."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)

    # Health probe for the platform. Declared as the one open endpoint and
    # returns no data; MCP itself stays protected.
    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def _healthz(_request: Any) -> Any:
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app(host=host, **kwargs)

    if token:
        app.add_middleware(BearerAuthMiddleware, token=token)

    return app


def run_http(
    server: Any,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    **kwargs: Any,
) -> None:
    """Serve an MCP server over streamable-http (blocking)."""
    app = build_http_app(
        server,
        auth_token=auth_token,
        host=host,
        allow_unauthenticated=allow_unauthenticated,
        **kwargs,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
