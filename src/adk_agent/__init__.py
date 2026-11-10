"""adk_agent - a reusable multi-agent framework built on Google ADK.

Two MCP directions:

* **incoming** - ADK agents consume external MCP servers' tools via
  :class:`google.adk.tools.mcp_tool.McpToolset`.
* **outgoing** - ADK agents are exposed as MCP servers via
  :func:`google.adk.tools.mcp_tool.to_mcp_server`, so Claude Code (or any
  MCP host) can drive them as a single tool named after the agent.
"""

from __future__ import annotations

from .config import (
    AgentConfig,
    FrameworkConfig,
    McpServerConfig,
    ModelConfig,
    load_config,
)
from .factory import build_agent, build_framework, build_runner
from .mcp.server import serve_agent, serve_many
from .models import build_model

__all__ = [
    "build_model",
    "build_agent",
    "build_framework",
    "build_runner",
    "serve_agent",
    "serve_many",
    "load_config",
    "ModelConfig",
    "McpServerConfig",
    "AgentConfig",
    "FrameworkConfig",
]

__version__ = "0.1.0"
