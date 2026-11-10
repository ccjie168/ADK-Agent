"""HTTP transport for MCP servers, with mandatory bearer-token auth (CP-S6).

Policy (see CLAUDE.md / ADR-0001): an MCP HTTP endpoint must declare auth.
Serving without a token is only allowed on a loopback host, and only when the
caller opts in explicitly with ``allow_unauthenticated=True``.
"""

from __future__ import annotations

from typing import Any

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
    **kwargs: Any,
) -> Any:
    """Build the streamable-http ASGI app, wrapping it in bearer auth if set."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    app = server.streamable_http_app(host=host, **kwargs)

    if auth_token:

        class BearerAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
                header = request.headers.get("authorization", "")
                parts = header.split(None, 1)
                valid = len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == auth_token
                if not valid:
                    return JSONResponse(
                        {"error": "unauthorized"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                return await call_next(request)

        app.add_middleware(BearerAuthMiddleware)

    return app


def run_http(
    server: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    **kwargs: Any,
) -> None:
    """Serve an MCP server over streamable-http (blocking)."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)
    app = build_http_app(server, auth_token=token, host=host, **kwargs)

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
