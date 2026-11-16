"""Install tool guards from an agent's declared or published grants."""

from __future__ import annotations

from typing import Any

from google.adk.agents import BaseAgent
from google.adk.tools import BaseTool
from google.adk.tools.base_toolset import BaseToolset

from ..core import AuditSink, ToolGrant, ToolGrantStore
from .guard import ToolGuard, install_tool_guard
from .policy import GrantPolicyEngine
from .sources import toolset_tool_ids


def declared_tool_ids(agent: Any) -> set[str]:
    """Collect the tool names an agent tree declares."""
    tool_ids: set[str] = set()
    for tool in getattr(agent, "tools", None) or ():
        if isinstance(tool, BaseTool):
            tool_ids.add(tool.name)
            continue
        if isinstance(tool, BaseToolset):
            tool_ids |= toolset_tool_ids(tool)
            continue
        name = getattr(tool, "__name__", None)
        if isinstance(name, str):
            tool_ids.add(name)
    for sub in getattr(agent, "sub_agents", None) or ():
        tool_ids |= declared_tool_ids(sub)
    return tool_ids


def install_declared_guards(
    agent: Any,
    audit: AuditSink | None,
    *,
    overlay: ToolGrantStore | None = None,
    grants: list[ToolGrant] | None = None,
) -> None:
    """Allow the agent's manifest grants, or its declared tools, and deny the rest.

    Non-ADK stand-ins are left untouched so a caller that only forwards the
    agent can pass a stub. A tool grant store, when given, is consulted for
    approved temporary grants outside the manifest. ``grants`` lets a caller
    that loaded an artifact directly supply the published manifest grants.
    """
    if not isinstance(agent, BaseAgent):
        return
    published = grants if grants is not None else getattr(agent, "_adk_tool_grants", None)
    if published is not None:
        allowed = list(published)
    else:
        allowed = [ToolGrant(tool_id=tool_id) for tool_id in sorted(declared_tool_ids(agent))]
    engine = GrantPolicyEngine(allowed, overlay=overlay)
    install_tool_guard(agent, ToolGuard(engine, audit=audit))
