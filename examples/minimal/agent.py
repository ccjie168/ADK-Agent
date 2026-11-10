"""Minimal ADK agent, exposed as an MCP server for Claude Code.

Run as a standalone MCP server (stdio):

    .venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py

Claude Code discovers it through the project-root ``.mcp.json``, which launches
this same command as a subprocess. The agent then appears to Claude Code as one
tool named ``minimal_agent``.
"""

import datetime

from google.adk.agents import LlmAgent

from adk_agent import build_model, serve_agent


def get_time() -> str:
    """Return the current local date and time in ISO 8601 format."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def echo(text: str) -> str:
    """Echo the given text straight back."""
    return text


agent = LlmAgent(
    name="minimal_agent",
    model=build_model(),
    description="A minimal ADK agent with a clock and an echo tool.",
    instruction=(
        "You are a helpful assistant. Use get_time when asked about the time, "
        "and echo when asked to repeat something."
    ),
    tools=[get_time, echo],
)


# ADK's own `adk web` / `adk run` look for `root_agent`.
root_agent = agent


if __name__ == "__main__":
    serve_agent(agent, transport="stdio")
