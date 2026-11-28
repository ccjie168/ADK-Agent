"""The ADK surface the outgoing MCP server depends on.

``_build_runner``, ``_run_agent`` and ``_reap_orphaned_sessions`` are ADK
internals (stable across the pinned ``google-adk>=2,<3`` range, not public
API).  They are resolved through the module at call time so tests can replace
them on ``google.adk.tools.mcp_tool._agent_to_mcp``.
"""

from __future__ import annotations

from typing import Any

from google.adk.dependencies._mcp import Context, ServerSession

__all__ = [
    "Context",
    "ServerSession",
    "build_runner",
    "is_in_memory_sessions",
    "new_server",
    "reap_orphaned_sessions",
    "run_agent",
    "to_mcp_server",
]


def _mcp_module() -> Any:
    from google.adk.tools.mcp_tool import _agent_to_mcp

    return _agent_to_mcp


def new_server(name: str, instructions: str | None = None) -> Any:
    from google.adk.dependencies._mcp import FastMCP

    return FastMCP(name=name, instructions=instructions)


def is_in_memory_sessions(service: Any) -> bool:
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    return isinstance(service, InMemorySessionService)


def to_mcp_server(agent: Any, **kwargs: Any) -> Any:
    from google.adk.tools.mcp_tool import to_mcp_server as build

    return build(agent, **kwargs)


def build_runner(agent: Any) -> Any:
    return _mcp_module()._build_runner(agent)


async def run_agent(*args: Any, **kwargs: Any) -> Any:
    return await _mcp_module()._run_agent(*args, **kwargs)


async def reap_orphaned_sessions(*args: Any, **kwargs: Any) -> Any:
    return await _mcp_module()._reap_orphaned_sessions(*args, **kwargs)
