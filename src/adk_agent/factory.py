"""Build ADK agents (and small multi-agent trees) from configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google.adk.agents import LlmAgent
from google.genai import types

from .config import AgentConfig, FrameworkConfig
from .core import SecretProvider
from .mcp.client import toolset_from_config
from .models import build_model
from .secretstore import EnvSecretProvider
from .tools.sources import openapi_toolset_from_config

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent
    from google.adk.runners import Runner


def build_agent(spec: AgentConfig, secrets: SecretProvider | None = None) -> BaseAgent:
    """Recursively build an ``LlmAgent`` from an :class:`AgentConfig`.

    Sub-agents are attached via ``sub_agents`` (ADK's hierarchical delegation),
    every configured external MCP server becomes a ``McpToolset`` tool, and
    every OpenAPI document becomes an ``OpenAPIToolset``. Header secrets default
    to :class:`EnvSecretProvider` and the same provider reaches sub-agents.
    """
    provider = secrets if secrets is not None else EnvSecretProvider()
    sub_agents = [build_agent(sub, provider) for sub in spec.sub_agents]
    tools = [toolset_from_config(server, provider) for server in spec.mcp_servers]
    tools += [openapi_toolset_from_config(cfg, provider) for cfg in spec.openapi]

    extra: dict[str, Any] = {}
    if spec.thinking_budget is not None:
        extra["generate_content_config"] = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=spec.thinking_budget)
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
