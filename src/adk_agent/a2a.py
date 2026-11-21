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

from .a2a_egress import AuditTransport
from .a2a_peer import (
    PeerAuthzMiddleware,
    PeerIdentityMiddleware,
    PeerTokenMiddleware,
    current_peer_principal,
)
from .audit.hashing import hash_text
from .auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from .core import AgentRef, Principal
from .mcp.http import resolve_port
from .ratelimit import RateLimit, RateLimitMiddleware, build_rate_limiter
from .runtime.audit_proxy import wrap_runner
from .tracing import resolve_trace_id

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent

    from .core import AgentManifest, AuditSink, IdentityProvider, QuotaConfig, QuotaManager

_INSTALL_HINT = (
    "A2A support needs the optional dependency; install it with "
    "`pip install 'a2a-sdk[http-server]>=0.3.4,<2'` "
    "(the range ADK 2.x declares for its a2a extra)."
)

_A2A_USER_ID = "a2a_user"
_A2A_TENANT = "local"

_EXPOSURE_ERROR = 'peer mode requires a manifest with exposure "a2a"'
_IDENTITY_ERROR = "peer mode requires exactly one of oidc or peer_tokens"
_STORES_ERROR = "peer mode requires both peers and peer_grants stores"
_PEER_ID_ERROR = "peer_id is required when audit is set"


def _peer_quota_policy(quota_config: QuotaConfig | None) -> Any:
    if quota_config is None:
        return None

    def policy_for(principal: Principal) -> Any:
        return quota_config.tenants.get(principal.tenant)

    return policy_for


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
    rate_limit: RateLimit | None = None,
    require_context: bool = False,
    oidc: IdentityProvider | None = None,
    peers: Any = None,
    peer_grants: Any = None,
    peer_tokens: dict[str, str] | None = None,
    manifest: AgentManifest | None = None,
    rag: Any | None = None,
) -> Any:
    """Build the A2A Starlette app. Legacy token mode or per-peer identity."""
    peer_mode = any(
        value is not None for value in (oidc, peers, peer_grants, peer_tokens, manifest)
    )
    if peer_mode:
        if manifest is None or manifest.exposure != "a2a":
            raise ValueError(_EXPOSURE_ERROR)
        if (oidc is None) == (peer_tokens is None):
            raise ValueError(_IDENTITY_ERROR)
        if peers is None or peer_grants is None:
            raise ValueError(_STORES_ERROR)

    audited = audit is not None or quota is not None or require_context
    if audited:
        if runner is None:
            from google.adk.tools.mcp_tool._agent_to_mcp import _build_runner

            runner = _build_runner(agent)
        principal: Any
        quota_policy: Any
        if peer_mode:
            principal = current_peer_principal
            quota_policy = _peer_quota_policy(quota_config)
        else:
            principal = Principal(tenant=_A2A_TENANT, subject=_A2A_USER_ID, kind="service")
            quota_policy = quota_config.tenants.get(_A2A_TENANT) if quota_config else None
        runner = wrap_runner(
            runner,
            agent_name=agent.name,
            principal=principal,
            input_text=None,
            audit=audit,
            quota=quota,
            quota_policy=quota_policy,
            trace_id=lambda: _current_trace_id.get(),
            source="a2a",
            require_context=require_context,
            rag=rag,
        )
    app = _to_a2a()(
        agent,
        host=host,
        port=port,
        rpc_path=rpc_path,
        runner=runner,
    )
    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="a2a"),
            surface="a2a",
            exempt=frozenset(),
        )
    if peer_mode:
        app.add_middleware(
            PeerAuthzMiddleware,
            agent_id=manifest.id if manifest is not None else agent.name,
            grants=peer_grants,
            audit=audit,
            trace_id=lambda: _current_trace_id.get(),
        )
        if oidc is not None:
            app.add_middleware(PeerIdentityMiddleware, peers=peers)
            app.add_middleware(OidcAuthMiddleware, provider=oidc, open_paths=frozenset())
        else:
            app.add_middleware(PeerTokenMiddleware, peers=peers, tokens=peer_tokens)
    elif auth_token:
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
    rate_limit: RateLimit | None = None,
    require_context: bool = False,
    oidc: IdentityProvider | None = None,
    peers: Any = None,
    peer_grants: Any = None,
    peer_tokens: dict[str, str] | None = None,
    manifest: AgentManifest | None = None,
    rag: Any | None = None,
) -> None:
    """Serve an agent over A2A (blocking). Peer mode replaces the shared token."""
    peer_mode = any(
        value is not None for value in (oidc, peers, peer_grants, peer_tokens, manifest)
    )
    token = None if peer_mode else resolve_http_auth(host, auth_token, allow_unauthenticated)
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
        rate_limit=rate_limit,
        require_context=require_context,
        oidc=oidc,
        peers=peers,
        peer_grants=peer_grants,
        peer_tokens=peer_tokens,
        manifest=manifest,
        rag=rag,
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
    audit: AuditSink | None = None,
    peer_id: str | None = None,
    tenant: str = "local",
    subject: str = "a2a_consumer",
) -> Any:
    """Build a ``RemoteA2aAgent``. With a token, card fetch and calls send it."""
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    client = None
    if audit is not None:
        if peer_id is None:
            raise ValueError(_PEER_ID_ERROR)
        import httpx

        agent_ref = AgentRef(
            id=name,
            version="remote",
            digest=f"sha256:{hash_text(agent_card)}",
        )
        client = httpx.AsyncClient(
            transport=AuditTransport(
                inner=httpx.AsyncHTTPTransport(),
                audit=audit,
                tenant=tenant,
                subject=subject,
                peer_id=peer_id,
                target=f"{peer_id}/{name}",
                agent_ref=agent_ref,
            ),
            headers=headers,
        )
    elif auth_token:
        import httpx

        client = httpx.AsyncClient(headers=headers)
    return _remote_a2a_agent()(
        name=name,
        agent_card=agent_card,
        description=description,
        timeout=timeout,
        httpx_client=client,
    )


__all__ = ["A2aUnavailable", "build_a2a_app", "remote_agent", "serve_a2a"]
