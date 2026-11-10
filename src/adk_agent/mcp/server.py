"""Outgoing MCP: expose ADK agents as MCP servers that Claude Code can call."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from google.adk.dependencies._mcp import Context, ServerSession

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent


def serve_agent(
    agent: BaseAgent,
    *,
    name: str | None = None,
    transport: Literal["stdio", "streamable-http"] = "stdio",
    runner: Any = None,
    instructions: str | None = None,
) -> Any:
    """Expose one ADK agent as an MCP server and run it (blocking).

    The whole agent -- its model loop and every tool it owns -- becomes a
    *single* MCP tool named after the agent. Any MCP host (Claude Code, an IDE,
    another agent) can call it with a plain ``request`` string.

    ``transport`` is ``"stdio"`` for local hosts or ``"streamable-http"`` for a
    networked deployment. Pass ``runner`` to plug in persistent session /
    artifact / memory services for a long-lived server.
    """
    from google.adk.tools.mcp_tool import to_mcp_server

    server = to_mcp_server(agent, name=name, runner=runner, instructions=instructions)
    server.run(transport=transport)
    return server


def serve_many(
    agents: dict[str, BaseAgent],
    *,
    name: str = "adk_agents",
    transport: Literal["stdio", "streamable-http"] = "stdio",
    instructions: str | None = None,
    runner_factory: Callable[[BaseAgent], Any] | None = None,
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
    from google.adk.dependencies._mcp import FastMCP
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.tools.mcp_tool._agent_to_mcp import (
        _build_runner,
        _reap_orphaned_sessions,
        _run_agent,
    )

    if not agents:
        raise ValueError("serve_many needs at least one agent")

    server = FastMCP(name=name, instructions=instructions)

    for tool_name, agent in agents.items():
        runner = runner_factory(agent) if runner_factory else _build_runner(agent)
        reap = isinstance(runner.session_service, InMemorySessionService)

        # One session map per tool, so separate tools keep separate conversations.
        sessions: Any = weakref.WeakKeyDictionary()
        created: set[str] = set()
        reap_failures: dict[str, int] = {}
        locks: Any = weakref.WeakKeyDictionary()

        def _make_tool(
            _runner: Any,
            _sessions: Any,
            _created: set[str],
            _reap_failures: dict[str, int],
            _locks: Any,
            _reap: bool,
        ) -> Callable[..., Any]:
            async def _tool(request: str, ctx: Context[ServerSession, Any]) -> list[Any]:
                if _reap:
                    await _reap_orphaned_sessions(_runner, _sessions, _created, _reap_failures)
                return await _run_agent(
                    _runner,
                    request,
                    ctx,
                    _sessions,
                    _created if _reap else None,
                    _locks,
                )

            return _tool

        tool_fn = _make_tool(runner, sessions, created, reap_failures, locks, reap)
        tool_fn.__name__ = f"call_{tool_name}"
        description = agent.description or f"Run the {tool_name} agent."

        server.add_tool(
            tool_fn,
            name=tool_name,
            description=description,
            structured_output=False,
        )

    server.run(transport=transport)
    return server
