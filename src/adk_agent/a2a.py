"""Optional A2A provider and consumer adapters (ADR-0003).

The ``a2a-sdk`` dependency is not part of the default install. Both builders
import ADK's A2A modules lazily and raise :class:`A2aUnavailable` when the
optional dependency is missing. Provider apps are always wrapped in the same
bearer middleware the MCP HTTP transport uses, including the agent card.
"""

from __future__ import annotations

import importlib
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import BearerAuthMiddleware, resolve_http_auth
from .core import Principal
from .mcp.http import resolve_port
from .runtime.audit_proxy import wrap_runner
from .tracing import resolve_trace_id

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

    from .core import AuditSink, QuotaConfig, QuotaManager

_INSTALL_HINT = (
    "A2A support needs the optional dependency; install it with "
    "`pip install 'a2a-sdk[http-server]>=0.3.4,<2'` "
    "(the range ADK 2.x declares for its a2a extra)."
)

_A2A_USER_ID = "a2a_user"
_A2A_TENANT = "local"

_current_trace_id: ContextVar[str | None] = ContextVar("a2a_trace_id", default=None)


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


class _TraceContextMiddleware:
    """Expose the request's trace id to the wrapped runner through a ContextVar."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        trace_id = resolve_trace_id(None, Headers(scope=scope).get("traceparent"))
        token = _current_trace_id.set(trace_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_trace_id.reset(token)


def build_a2a_app(
    agent: BaseAgent,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    rpc_path: str = "",
    runner: Any = None,
    auth_token: str | None = None,
    audit: AuditSink | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
) -> Any:
    """Build the A2A Starlette app. A token protects every path, card included."""
    audited = audit is not None or quota is not None
    if audited:
        if runner is None:
            from google.adk.tools.mcp_tool._agent_to_mcp import _build_runner

            runner = _build_runner(agent)
        runner = wrap_runner(
            runner,
            agent_name=agent.name,
            principal=Principal(tenant=_A2A_TENANT, subject=_A2A_USER_ID, kind="service"),
            input_text=None,
            audit=audit,
            quota=quota,
            quota_policy=quota_config.tenants.get(_A2A_TENANT) if quota_config else None,
            trace_id=lambda: _current_trace_id.get(),
            source="a2a",
        )
    app = _to_a2a()(
        agent,
        host=host,
        port=port,
        rpc_path=rpc_path,
        runner=runner,
    )
    if auth_token:
        app.add_middleware(BearerAuthMiddleware, token=auth_token, open_paths=frozenset())
    if audited:
        app.add_middleware(_TraceContextMiddleware)
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
    audit: AuditSink | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
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
        audit=audit,
        quota=quota,
        quota_config=quota_config,
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
