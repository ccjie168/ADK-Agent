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
    OpenApiConfig,
    load_config,
)
from .console import build_console_app, run_console
from .factory import build_agent, build_framework, build_runner
from .mcp.server import serve_agent, serve_many
from .models import build_model, disable_thinking
from .sandbox import (
    SandboxPolicy,
    SandboxTimeout,
    SandboxViolation,
    ToolSandbox,
    install_tool_sandbox,
)
from .secretstore import EnvSecretProvider, MappingSecretProvider, SecretNotFound

__all__ = [
    "build_model",
    "disable_thinking",
    "build_agent",
    "build_framework",
    "build_runner",
    "serve_agent",
    "serve_many",
    "build_console_app",
    "run_console",
    "load_config",
    "ModelConfig",
    "McpServerConfig",
    "OpenApiConfig",
    "AgentConfig",
    "FrameworkConfig",
    "EnvSecretProvider",
    "MappingSecretProvider",
    "SecretNotFound",
    "SandboxPolicy",
    "SandboxTimeout",
    "SandboxViolation",
    "ToolSandbox",
    "install_tool_sandbox",
]

__version__ = "0.1.0"
