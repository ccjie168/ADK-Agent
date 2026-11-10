"""Call an ADK agent (exposed over MCP stdio) with one request string.

Usage:
    python scripts/call_tool.py "<request>" [--tool NAME] -- <command> [args...]

Example:
    PYTHONPATH=src python scripts/call_tool.py "What time is it?" -- \
        .venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py

Unlike ``probe_mcp.py`` (which only lists tools), this actually invokes the
agent, so the model backend must be reachable and authenticated.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_TOOL = "minimal_agent"


async def call(cmd_argv: list[str], tool_name: str, request: str) -> None:
    params = StdioServerParameters(
        command=cmd_argv[0],
        args=cmd_argv[1:],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(tool_name, {"request": request})
        print("isError:", getattr(result, "is_error", None))
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                print(text)
            else:
                print(f"[{type(block).__name__}]")


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        raise SystemExit(__doc__)

    tool = DEFAULT_TOOL
    if "--tool" in argv:
        i = argv.index("--tool")
        tool = argv[i + 1]
        del argv[i : i + 2]

    if "--" in argv:
        i = argv.index("--")
        request = " ".join(argv[:i]).strip() or "Hello, what can you do?"
        cmd_argv = argv[i + 1 :]
    else:
        request = " ".join(argv).strip() or "Hello, what can you do?"
        cmd_argv = []

    if not cmd_argv:
        raise SystemExit("missing `-- <command> [args...]`")

    asyncio.run(call(cmd_argv, tool, request))


if __name__ == "__main__":
    main()
