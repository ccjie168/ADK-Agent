"""Incoming MCP: let ADK agents consume external MCP servers' tools."""

from __future__ import annotations

from typing import Any

from ..config import McpServerConfig
from ..core import SecretProvider
from ..secretstore import secret_header_provider


def toolset_from_config(cfg: McpServerConfig, secrets: SecretProvider | None = None):
    """Build an ``McpToolset`` from an :class:`McpServerConfig`.

    ``transport="stdio"`` launches a local process; ``transport="http"``
    reaches a streamable-HTTP MCP server over the network. ``header_secrets``
    are resolved per request through ``secrets``.
    """
    from google.adk.tools.mcp_tool import (
        McpToolset,
        StdioConnectionParams,
        StreamableHTTPConnectionParams,
    )

    params: Any
    if cfg.transport == "stdio":
        from mcp import StdioServerParameters

        if not cfg.command:
            raise ValueError("stdio MCP server config needs a `command`")
        params = StdioConnectionParams(
            server_params=StdioServerParameters(
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
            ),
            timeout=cfg.timeout,
        )
    else:
        if not cfg.url:
            raise ValueError("http MCP server config needs a `url`")
        params = StreamableHTTPConnectionParams(
            url=cfg.url,
            headers=cfg.headers,
            timeout=cfg.timeout,
            sse_read_timeout=cfg.sse_read_timeout,
        )

    kwargs: dict = {"connection_params": params}
    if cfg.tool_filter:
        kwargs["tool_filter"] = cfg.tool_filter
    if cfg.tool_name_prefix:
        kwargs["tool_name_prefix"] = cfg.tool_name_prefix
    if cfg.header_secrets:
        if secrets is None:
            raise ValueError("header_secrets need a SecretProvider")
        kwargs["header_provider"] = secret_header_provider(secrets, cfg.header_secrets)

    return McpToolset(**kwargs)
