"""HTTP transport for MCP servers, with mandatory bearer-token auth (CP-S6).

Policy (see CLAUDE.md / ADR-0001): an MCP HTTP endpoint must declare auth.
Serving without a token is only allowed on a loopback host, and only when the
caller opts in explicitly with ``allow_unauthenticated=True``.
"""

from __future__ import annotations

import os
from typing import Any

from starlette.responses import JSONResponse, PlainTextResponse

from ..auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from ..core import IdentityProvider
from ..metrics import MetricsRegistry
from ..ratelimit import FixedWindowLimiter, RateLimit, RateLimitMiddleware


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


def build_http_app(
    server: Any,
    *,
    auth_token: str | None,
    host: str = "127.0.0.1",
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    metrics: MetricsRegistry | None = None,
    rate_limit: RateLimit | None = None,
    **kwargs: Any,
) -> Any:
    """Build the streamable-http ASGI app, wrapping it in bearer auth if set."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None

    # Health probe for the platform. Declared as the one open endpoint and
    # returns no data; MCP itself stays protected.
    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def _healthz(_request: Any) -> Any:
        return JSONResponse({"status": "ok"})

    if metrics is not None:

        @server.custom_route("/metrics", methods=["GET"], include_in_schema=False)
        async def _metrics(_request: Any) -> Any:
            return PlainTextResponse(
                metrics.render(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

    app = server.streamable_http_app(host=host, **kwargs)

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=FixedWindowLimiter(rate_limit.limit, rate_limit.window_seconds),
            surface="mcp",
            metrics=metrics,
            exempt=frozenset({"/healthz", "/metrics"}),
        )

    if oidc is not None:
        app.add_middleware(OidcAuthMiddleware, provider=oidc)
    elif token:
        app.add_middleware(BearerAuthMiddleware, token=token)

    return app


def run_http(
    server: Any,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    metrics: MetricsRegistry | None = None,
    rate_limit: RateLimit | None = None,
    **kwargs: Any,
) -> None:
    """Serve an MCP server over streamable-http (blocking)."""
    app = build_http_app(
        server,
        auth_token=auth_token,
        host=host,
        allow_unauthenticated=allow_unauthenticated,
        oidc=oidc,
        metrics=metrics,
        rate_limit=rate_limit,
        **kwargs,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolve_port(port), log_level="info")
