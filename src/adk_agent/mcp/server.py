"""Outgoing MCP: expose ADK agents as MCP servers that Claude Code can call."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ..adapters.adk.mcp import (
    Context,
    ServerSession,
    build_runner,
    is_in_memory_sessions,
    new_server,
    reap_orphaned_sessions,
    run_agent,
    to_mcp_server,
)
from ..core import Principal
from ..runtime.sessions import scoped_user_id, session_tenant
from ..tracing import trace_id_from_traceparent
from .runtime import wrap_runner

if TYPE_CHECKING:  # pragma: no cover
    from ..adapters.adk.agents import BaseAgent
    from ..core import AuditSink, IdentityProvider, QuotaConfig, QuotaManager
    from ..metrics import MetricsRegistry
    from ..ratelimit import RateLimit

_MCP_USER_ID = "mcp_user"
_MAX_REAP_ATTEMPTS = 3


def _principal_from_ctx(ctx: Any) -> Principal | None:
    try:
        request = ctx.request_context.request
    except Exception:
        return None
    return getattr(getattr(request, "state", None), "principal", None)


def _session_user(principal: Principal, tenant_scope: bool) -> str:
    return scoped_user_id(principal) if tenant_scope else principal.subject


def _trace_id_from_ctx(ctx: Any) -> str | None:
    try:
        request = ctx.request_context.request
        headers = getattr(request, "headers", None)
        if headers is None:
            return None
        return trace_id_from_traceparent(headers.get("traceparent"))
    except Exception:
        return None


class _PrincipalSessionService:
    """Session service proxy that attributes every call to the token subject."""

    def __init__(self, inner: Any, principal: Principal, *, tenant_scope: bool = False) -> None:
        self._inner = inner
        self._principal = principal
        self._tenant_scope = tenant_scope

    def _user_id(self) -> str:
        return _session_user(self._principal, self._tenant_scope)

    async def create_session(self, *, app_name, user_id, state=None, session_id=None):
        merged = dict(state or {})
        merged["principal"] = self._principal.model_dump(mode="json")
        with session_tenant(self._principal.tenant):
            return await self._inner.create_session(
                app_name=app_name,
                user_id=self._user_id(),
                state=merged,
                session_id=session_id,
            )

    async def get_session(self, *, app_name, user_id, session_id, config=None):
        with session_tenant(self._principal.tenant):
            return await self._inner.get_session(
                app_name=app_name,
                user_id=self._user_id(),
                session_id=session_id,
                config=config,
            )

    async def delete_session(self, *, app_name, user_id, session_id):
        with session_tenant(self._principal.tenant):
            return await self._inner.delete_session(
                app_name=app_name,
                user_id=self._user_id(),
                session_id=session_id,
            )

    async def list_sessions(self, *, app_name, user_id=None):
        with session_tenant(self._principal.tenant):
            return await self._inner.list_sessions(
                app_name=app_name,
                user_id=self._user_id(),
            )

    async def append_event(self, session, event):
        with session_tenant(self._principal.tenant):
            return await self._inner.append_event(session, event)

    async def get_user_state(self, *, app_name, user_id):
        with session_tenant(self._principal.tenant):
            return await self._inner.get_user_state(
                app_name=app_name,
                user_id=self._user_id(),
            )

    async def flush(self):
        with session_tenant(self._principal.tenant):
            return await self._inner.flush()

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _PrincipalRunner:
    """Runner proxy that runs the agent as the token subject."""

    def __init__(self, runner: Any, principal: Principal, *, tenant_scope: bool = False) -> None:
        self._runner = runner
        self._principal = principal
        self._tenant_scope = tenant_scope
        self.app_name = runner.app_name
        self.session_service = _PrincipalSessionService(
            runner.session_service, principal, tenant_scope=tenant_scope
        )

    def run_async(self, *, user_id, **kwargs):
        return self._runner.run_async(
            user_id=_session_user(self._principal, self._tenant_scope), **kwargs
        )

    def __getattr__(self, name):
        return getattr(self._runner, name)


@dataclass
class _ScopedState:
    sessions: Any
    created: set[str]
    reap_failures: dict[str, int]
    locks: Any


def _state_for(states: dict[str, _ScopedState], subject: str) -> _ScopedState:
    state = states.get(subject)
    if state is None:
        state = _ScopedState(weakref.WeakKeyDictionary(), set(), {}, weakref.WeakKeyDictionary())
        states[subject] = state
    return state


async def _reap_as(
    runner: Any,
    sessions: Any,
    created: set[str],
    reap_failures: dict[str, int],
) -> None:
    live = set(sessions.values())
    for session_id in created - live:
        if session_id not in created:
            continue
        created.discard(session_id)
        try:
            # The principal proxy rewrites this user id to the token subject.
            await runner.session_service.delete_session(
                app_name=runner.app_name,
                user_id=_MCP_USER_ID,
                session_id=session_id,
            )
            reap_failures.pop(session_id, None)
        except Exception:
            attempts = reap_failures.get(session_id, 0) + 1
            if attempts < _MAX_REAP_ATTEMPTS:
                reap_failures[session_id] = attempts
                created.add(session_id)
            else:
                reap_failures.pop(session_id, None)
        except BaseException:
            created.add(session_id)
            raise


def serve_agent(
    agent: BaseAgent,
    *,
    name: str | None = None,
    transport: Literal["stdio", "streamable-http"] = "stdio",
    runner: Any = None,
    instructions: str | None = None,
    host: str = "127.0.0.1",
    port: int | None = None,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    audit: AuditSink | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    metrics: MetricsRegistry | None = None,
    rate_limit: RateLimit | None = None,
    session_tenant_scope: bool = False,
    tool_guard: bool = False,
    rag: Any | None = None,
) -> Any:
    """Expose one ADK agent as an MCP server and run it (blocking).

    The whole agent -- its model loop and every tool it owns -- becomes a
    *single* MCP tool named after the agent. Any MCP host (Claude Code, an IDE,
    another agent) can call it with a plain ``request`` string.

    ``transport`` is ``"stdio"`` for local hosts or ``"streamable-http"`` for a
    networked deployment. HTTP requires ``auth_token`` (CP-S6); set
    ``allow_unauthenticated=True`` only for a loopback dev server. Pass
    ``runner`` to plug in persistent session / artifact / memory services for a
    long-lived server.
    """
    if rate_limit is not None and transport != "streamable-http":
        raise ValueError("rate limit requires streamable-http")

    if (
        (transport == "streamable-http" and oidc is not None)
        or audit is not None
        or quota is not None
        or quota_config is not None
        or metrics is not None
        or rate_limit is not None
        or tool_guard
        or rag is not None
    ):
        tool_name = name or agent.name
        return serve_many(
            {tool_name: agent},
            name=tool_name,
            transport=transport,
            instructions=instructions,
            runner_factory=(lambda _agent: runner) if runner is not None else None,
            host=host,
            port=port,
            auth_token=auth_token,
            allow_unauthenticated=allow_unauthenticated,
            oidc=oidc,
            audit=audit,
            quota=quota,
            quota_config=quota_config,
            metrics=metrics,
            rate_limit=rate_limit,
            session_tenant_scope=session_tenant_scope,
            tool_guard=tool_guard,
            rag_for=(lambda _tool_name: rag) if rag is not None else None,
        )

    server = to_mcp_server(agent, name=name, runner=runner, instructions=instructions)
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        from .http import run_http

        run_http(
            server,
            host=host,
            port=port,
            auth_token=auth_token,
            allow_unauthenticated=allow_unauthenticated,
            oidc=oidc,
            metrics=metrics,
            rate_limit=rate_limit,
        )
    return server


def serve_many(
    agents: dict[str, BaseAgent],
    *,
    name: str = "adk_agents",
    transport: Literal["stdio", "streamable-http"] = "stdio",
    instructions: str | None = None,
    runner_factory: Callable[[BaseAgent], Any] | None = None,
    host: str = "127.0.0.1",
    port: int | None = None,
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    audit: AuditSink | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    metrics: MetricsRegistry | None = None,
    rate_limit: RateLimit | None = None,
    session_tenant_scope: bool = False,
    tool_guard: bool = False,
    rag_for: Callable[[str], Any] | None = None,
) -> Any:
    """Expose several ADK agents as separate MCP tools in one server.

    Each key in ``agents`` becomes one MCP tool that runs that agent. Sessions,
    progress notifications and multimodal output behave exactly as in
    :func:`serve_agent`, because this reuses ADK's per-connection runner logic
    (``_run_agent`` in ``google.adk.tools.mcp_tool._agent_to_mcp``).

    ``runner_factory`` lets you inject persistent services per agent, e.g.
    ``lambda agent: Runner(app_name=agent.name, agent=agent,
    session_service=my_session_service)``.

    Note: this deliberately depends on ADK's internal ``_agent_to_mcp`` helpers,
    which are stable across the pinned ``google-adk>=2,<3`` range but are not
    public API.
    """
    if not agents:
        raise ValueError("serve_many needs at least one agent")
    if rate_limit is not None and transport != "streamable-http":
        raise ValueError("rate limit requires streamable-http")

    server = new_server(name, instructions)

    for tool_name, agent in agents.items():
        runner = runner_factory(agent) if runner_factory else build_runner(agent)
        reap = is_in_memory_sessions(runner.session_service)
        rag = rag_for(tool_name) if rag_for is not None else None

        # One session map per tool, so separate tools keep separate conversations.
        anonymous_state = _ScopedState(
            weakref.WeakKeyDictionary(), set(), {}, weakref.WeakKeyDictionary()
        )
        state_by_subject: dict[str, _ScopedState] = {}

        def _make_tool(
            _runner: Any,
            _anonymous_state: _ScopedState,
            _state_by_subject: dict[str, _ScopedState],
            _reap: bool,
            _agent_name: str,
            _audit: AuditSink | None,
            _quota: QuotaManager | None,
            _quota_config: QuotaConfig | None,
            _metrics: MetricsRegistry | None,
            _tenant_scope: bool,
            _tool_guard: bool,
            _rag: Any | None,
        ) -> Callable[..., Any]:
            async def _tool(request: str, ctx: Context[ServerSession, Any]) -> list[Any]:
                principal = _principal_from_ctx(ctx)
                if principal is None:
                    state = _anonymous_state
                    scoped_runner = _runner
                else:
                    scoped_key = _session_user(principal, _tenant_scope)
                    state = _state_for(_state_by_subject, scoped_key)
                    scoped_runner = _PrincipalRunner(_runner, principal, tenant_scope=_tenant_scope)
                if _reap:
                    if principal is None:
                        await reap_orphaned_sessions(
                            _runner,
                            state.sessions,
                            state.created,
                            state.reap_failures,
                        )
                    else:
                        await _reap_as(
                            scoped_runner,
                            state.sessions,
                            state.created,
                            state.reap_failures,
                        )
                run_principal = principal or Principal(
                    tenant="local", subject=_MCP_USER_ID, kind="service"
                )
                policy = _quota_config.tenants.get(run_principal.tenant) if _quota_config else None
                if (
                    _audit is not None
                    or _quota is not None
                    or _metrics is not None
                    or _tool_guard
                    or _rag is not None
                ):
                    scoped_runner = wrap_runner(
                        scoped_runner,
                        agent_name=_agent_name,
                        principal=run_principal,
                        input_text=request,
                        audit=_audit,
                        quota=_quota,
                        quota_policy=policy,
                        trace_id=_trace_id_from_ctx(ctx),
                        metrics=_metrics,
                        source="mcp",
                        require_context=_tool_guard,
                        rag=_rag,
                    )
                return await run_agent(
                    scoped_runner,
                    request,
                    ctx,
                    state.sessions,
                    state.created if _reap else None,
                    state.locks,
                )

            return _tool

        tool_fn = _make_tool(
            runner,
            anonymous_state,
            state_by_subject,
            reap,
            agent.name,
            audit,
            quota,
            quota_config,
            metrics,
            session_tenant_scope,
            tool_guard,
            rag,
        )
        tool_fn.__name__ = f"call_{tool_name}"
        description = agent.description or f"Run the {tool_name} agent."

        server.add_tool(
            tool_fn,
            name=tool_name,
            description=description,
            structured_output=False,
        )

    if transport == "stdio":
        server.run(transport="stdio")
    else:
        from .http import run_http

        run_http(
            server,
            host=host,
            port=port,
            auth_token=auth_token,
            allow_unauthenticated=allow_unauthenticated,
            oidc=oidc,
            metrics=metrics,
            rate_limit=rate_limit,
        )
    return server
