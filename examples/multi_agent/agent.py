"""Multi-agent orchestration, exposed as one MCP tool for Claude Code.

An orchestrator delegates to two specialists:

* ``math_agent`` - ``add`` / ``multiply``
* ``time_agent`` - ``get_time``

Run:

    .venv/Scripts/python.exe -m adk_agent serve --agent examples/multi_agent/agent.py

Claude Code then sees a single tool, ``orchestrator``, which routes to the right
specialist behind the scenes.
"""

import datetime

from google.adk.agents import LlmAgent

from adk_agent import build_model, disable_thinking, serve_agent


def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


def get_time() -> str:
    """Return the current local date and time in ISO 8601 format."""
    return datetime.datetime.now().isoformat(timespec="seconds")


math_agent = LlmAgent(
    name="math_agent",
    model=build_model(),
    description="Does arithmetic: adds and multiplies two numbers.",
    instruction="Use add/multiply to answer arithmetic questions. Reply with just the result.",
    tools=[add, multiply],
    generate_content_config=disable_thinking(),
)

time_agent = LlmAgent(
    name="time_agent",
    model=build_model(),
    description="Reports the current date and time.",
    instruction="Use get_time to answer questions about the current time.",
    tools=[get_time],
    generate_content_config=disable_thinking(),
)

orchestrator = LlmAgent(
    name="orchestrator",
    model=build_model(),
    description="Routes a request to math_agent or time_agent and summarizes the answer.",
    instruction=(
        "You coordinate two specialists. Delegate arithmetic to math_agent and "
        "questions about the current time to time_agent. Then summarize their "
        "answer for the user."
    ),
    sub_agents=[math_agent, time_agent],
    generate_content_config=disable_thinking(),
)

# Default entry point for `adk-agent serve --agent examples/multi_agent/agent.py`.
agent = orchestrator
# ADK's own `adk web` / `adk run` look for `root_agent`.
root_agent = orchestrator

# Consumed by `adk-agent serve-many --agents examples/multi_agent/agent.py`.
agents = {"math_agent": math_agent, "time_agent": time_agent}


if __name__ == "__main__":
    serve_agent(orchestrator, transport="stdio")
