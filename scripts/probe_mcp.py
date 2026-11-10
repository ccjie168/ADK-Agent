"""Probe an MCP server over stdio: initialize the session and list its tools.

Usage:
    python scripts/probe_mcp.py -- <command> [args...]

Example:
    PYTHONPATH=src python scripts/probe_mcp.py -- \
        .venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py

This is the same handshake Claude Code performs when it launches a stdio MCP
server from ``.mcp.json``. It needs no API key: ``list_tools`` does not call the
model, so a missing key only affects an actual tool *call*.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def probe(cmd_argv: list[str]) -> None:
    params = StdioServerParameters(
        command=cmd_argv[0],
        args=cmd_argv[1:],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
        proto = getattr(init, "protocol_version", None) or getattr(init, "protocolVersion", None)
        print("server:", info)
        print("protocol:", proto)
        tools = await session.list_tools()
        print("tools:", len(tools.tools))
        for tool in tools.tools:
            schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
            print(" -", tool.name)
            print("   desc:", tool.description)
            print("   schema:", json.dumps(schema, ensure_ascii=False, default=str))


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise SystemExit(__doc__)
    asyncio.run(probe(argv))


if __name__ == "__main__":
    main()
