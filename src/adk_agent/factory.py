"""Build ADK agents (and small multi-agent trees) from configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google.adk.agents import LlmAgent
from google.genai import types

from .config import AgentConfig, FrameworkConfig
from .mcp.client import toolset_from_config
from .models import build_model

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent
    from google.adk.runners import Runner


def build_agent(spec: AgentConfig) -> BaseAgent:
    """Recursively build an ``LlmAgent`` from an :class:`AgentConfig`.

    Sub-agents are attached via ``sub_agents`` (ADK's hierarchical delegation),
    and every configured external MCP server becomes a ``McpToolset`` tool.
    """
    sub_agents = [build_agent(sub) for sub in spec.sub_agents]
    tools = [toolset_from_config(server) for server in spec.mcp_servers]

    extra: dict[str, Any] = {}
    if spec.model.thinking_budget is not None:
        extra["generate_content_config"] = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=spec.model.thinking_budget)
        )

    return LlmAgent(
        name=spec.name,
        model=build_model(spec.model),
        description=spec.description,
        instruction=spec.instruction,
        tools=tools,
        sub_agents=sub_agents,
        **extra,
    )


def build_framework(cfg: FrameworkConfig) -> dict[str, BaseAgent]:
    """Build every agent named in a :class:`FrameworkConfig`."""
    return {name: build_agent(spec) for name, spec in cfg.agents.items()}


def build_runner(agent: BaseAgent, session_db: str | None = None) -> Runner | None:
    """Return a Runner with a persistent SQLite session store, or ``None``.

    ``None`` means "let ADK use its in-memory default". Supply ``session_db``
    (the CLI reads ``SESSION_DB``) to keep sessions across restarts, which a
    real deployment needs. The parent directory is created if missing.
    """
    if not session_db:
        return None

    from pathlib import Path

    from google.adk.runners import Runner
    from google.adk.sessions.sqlite_session_service import SqliteSessionService

    db_path = Path(session_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Runner(
        app_name=agent.name,
        agent=agent,
        session_service=SqliteSessionService(str(db_path)),
    )
