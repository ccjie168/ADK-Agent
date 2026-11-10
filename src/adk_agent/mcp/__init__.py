"""MCP helpers for both directions.

* ``client`` - ADK agents consume external MCP servers' tools (``McpToolset``).
* ``server`` - ADK agents are exposed as MCP servers (``to_mcp_server``).
"""

from .client import toolset_from_config
from .server import serve_agent, serve_many

__all__ = ["toolset_from_config", "serve_agent", "serve_many"]
