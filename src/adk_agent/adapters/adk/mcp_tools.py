"""ADK MCP toolset construction for external MCP servers (incoming tools)."""

from __future__ import annotations

from typing import Any

__all__ = ["http_params", "mcp_toolset", "stdio_params"]


def stdio_params(*, server_params: Any, timeout: float = 5.0) -> Any:
    from google.adk.tools.mcp_tool import StdioConnectionParams

    return StdioConnectionParams(server_params=server_params, timeout=timeout)


def http_params(**kwargs: Any) -> Any:
    from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams

    return StreamableHTTPConnectionParams(**kwargs)


def mcp_toolset(**kwargs: Any) -> Any:
    from google.adk.tools.mcp_tool import McpToolset

    return McpToolset(**kwargs)
