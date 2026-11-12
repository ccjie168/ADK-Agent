"""Optional A2A provider and consumer adapters (ADR-0003).

The ``a2a-sdk`` dependency is not part of the default install. Both builders
import ADK's A2A modules lazily and raise :class:`A2aUnavailable` when the
optional dependency is missing. Provider apps are always wrapped in the same
bearer middleware the MCP HTTP transport uses, including the agent card.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .auth import BearerAuthMiddleware, resolve_http_auth
from .mcp.http import resolve_port

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

_INSTALL_HINT = (
    "A2A support needs the optional dependency; install it with "
    "`pip install 'a2a-sdk[http-server]>=0.3.4,<2'` "
    "(the range ADK 2.x declares for its a2a extra)."
)


class A2aUnavailable(RuntimeError):
    """The optional A2A dependency is not installed."""


def _import_module(name: str) -> Any:
    """Indirection so tests can simulate a missing optional dependency."""
    return importlib.import_module(name)


def _to_a2a() -> Any:
    try:
        return _import_module("google.adk.a2a.utils.agent_to_a2a").to_a2a
    except ImportError as exc:
        raise A2aUnavailable(_INSTALL_HINT) from exc


def _remote_a2a_agent() -> Any:
    try:
        return _import_module("google.adk.a2a.agent._remote_a2a_agent").RemoteA2aAgent
    except ImportError as exc:
        raise A2aUnavailable(_INSTALL_HINT) from exc


def build_a2a_app(
    agent: BaseAgent,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    rpc_path: str = "",
    runner: Any = None,
    auth_token: str | None = None,
) -> Any:
    """Build the A2A Starlette app. A token protects every path, card included."""
    app = _to_a2a()(
        agent,
        host=host,
        port=port,
        rpc_path=rpc_path,
        runner=runner,
    )
    if auth_token:
        app.add_middleware(BearerAuthMiddleware, token=auth_token, open_paths=frozenset())
    return app


def serve_a2a(
    agent: BaseAgent,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    rpc_path: str = "",
    runner: Any = None,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
) -> None:
    """Serve an agent over A2A (blocking). Network binds require a token."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated)
    resolved_port = resolve_port(port)
    app = build_a2a_app(
        agent,
        host=host,
        port=resolved_port,
        rpc_path=rpc_path,
        runner=runner,
        auth_token=token,
    )

    import uvicorn

    uvicorn.run(app, host=host, port=resolved_port, log_level="info")


def remote_agent(
    name: str,
    agent_card: str,
    *,
    description: str = "",
    timeout: float = 600.0,
    auth_token: str | None = None,
) -> Any:
    """Build a ``RemoteA2aAgent``. With a token, card fetch and calls send it."""
    client = None
    if auth_token:
        import httpx

        client = httpx.AsyncClient(headers={"Authorization": f"Bearer {auth_token}"})
    return _remote_a2a_agent()(
        name=name,
        agent_card=agent_card,
        description=description,
        timeout=timeout,
        httpx_client=client,
    )


__all__ = ["A2aUnavailable", "build_a2a_app", "remote_agent", "serve_a2a"]
