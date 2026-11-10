"""Build ADK agents (and small multi-agent trees) from configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from .config import AgentConfig, FrameworkConfig
from .mcp.client import toolset_from_config
from .models import build_model

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent


def build_agent(spec: AgentConfig) -> BaseAgent:
    """Recursively build an ``LlmAgent`` from an :class:`AgentConfig`.

    Sub-agents are attached via ``sub_agents`` (ADK's hierarchical delegation),
    and every configured external MCP server becomes a ``McpToolset`` tool.
    """
    sub_agents = [build_agent(sub) for sub in spec.sub_agents]
    tools = [toolset_from_config(server) for server in spec.mcp_servers]

    return LlmAgent(
        name=spec.name,
        model=build_model(spec.model),
        description=spec.description,
        instruction=spec.instruction,
        tools=tools,
        sub_agents=sub_agents,
    )


def build_framework(cfg: FrameworkConfig) -> dict[str, BaseAgent]:
    """Build every agent named in a :class:`FrameworkConfig`."""
    return {name: build_agent(spec) for name, spec in cfg.agents.items()}
