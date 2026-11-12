"""Build ADK agents (and small multi-agent trees) from configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google.adk.agents import LlmAgent
from google.genai import types

from .config import AgentConfig, FrameworkConfig
from .core import SecretProvider
from .mcp.client import toolset_from_config
from .models import build_model
from .sandbox import check_url
from .secretstore import EnvSecretProvider
from .tools.sources import load_openapi_spec, openapi_toolset_from_config

if TYPE_CHECKING:  # pragma: no cover
    from google.adk.agents import BaseAgent
    from google.adk.runners import Runner


def _check_egress(spec: AgentConfig) -> None:
    """Deny HTTP tool sources outside the configured host allowlist."""
    for server in spec.mcp_servers:
        if server.transport == "http" and server.url:
            check_url(server.url, spec.sandbox)
    if spec.sandbox.allowed_hosts is None:
        return
    for api in spec.openapi:
        document = load_openapi_spec(api.spec_path)
        for server in document.get("servers", []) or []:
            url = server.get("url") if isinstance(server, dict) else None
            if isinstance(url, str):
                check_url(url, spec.sandbox)


def build_agent(spec: AgentConfig, secrets: SecretProvider | None = None) -> BaseAgent:
    """Recursively build an ``LlmAgent`` from an :class:`AgentConfig`.

    Sub-agents are attached via ``sub_agents`` (ADK's hierarchical delegation),
    every configured external MCP server becomes a ``McpToolset`` tool, and
    every OpenAPI document becomes an ``OpenAPIToolset``. Header secrets default
    to :class:`EnvSecretProvider` and the same provider reaches sub-agents. HTTP
    tool sources are checked against the sandbox host allowlist first.
    """
    _check_egress(spec)
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
    """Return a Runner with the configured session store, or ``None``.

    ``None`` means "let ADK use its in-memory default". ``SESSION_URL`` selects
    a shared store (Postgres) for horizontally scaled workers; ``session_db``
    (the CLI reads ``SESSION_DB``) keeps sessions in SQLite for single-node
    demos. See ADR-0005.
    """
    from .runtime.sessions import configured_session_service

    service = configured_session_service(session_db)
    if service is None:
        return None

    from google.adk.runners import Runner

    return Runner(app_name=agent.name, agent=agent, session_service=service)
