"""Pydantic configuration schema for adk-agent.

These models describe an agent, the LLM backend it uses, and the external MCP
servers it should consume tools from. The same schema is used by the model
factory, the agent factory, and (later) the CLI's ``new``/``serve`` commands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelConfig(BaseModel):
    """Which LLM backend an agent runs on."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "litellm", "claude", "vertex"] = "litellm"
    # LiteLLM model id (e.g. "deepseek/deepseek-v4-pro", "openai/gpt-4o") or
    # an ADK model id for the gemini/claude providers.
    name: str = "deepseek/deepseek-v4-pro"
    api_key: str | None = None
    api_base: str | None = None
    # Set to cap or disable model thinking (0 disables it), e.g. for
    # Anthropic-compatible endpoints that reject redacted_thinking history.
    thinking_budget: int | None = None
    # Extra keyword arguments forwarded to the ADK model class.
    kwargs: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(BaseModel):
    """How to reach one external MCP server (the *incoming* direction)."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "http"] = "stdio"

    # --- stdio transport ---
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None

    # --- http transport ---
    url: str | None = None
    headers: dict[str, str] | None = None

    # --- shared ---
    timeout: float = 5.0
    sse_read_timeout: float = 300.0
    tool_filter: list[str] | None = None
    tool_name_prefix: str | None = None


class AgentConfig(BaseModel):
    """Declarative description of one ADK agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    instruction: str = ""
    model: ModelConfig = Field(default_factory=ModelConfig)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    sub_agents: list[AgentConfig] = Field(default_factory=list)


class FrameworkConfig(BaseModel):
    """Top-level config: named agents plus which one to expose over MCP."""

    model_config = ConfigDict(extra="forbid")

    agents: dict[str, AgentConfig]
    expose: str | None = None
    transport: Literal["stdio", "streamable-http"] = "stdio"

    @model_validator(mode="after")
    def _expose_must_exist(self) -> FrameworkConfig:
        if self.expose is not None and self.expose not in self.agents:
            raise ValueError(f"expose {self.expose!r} is not in agents")
        return self


AgentConfig.model_rebuild()


def load_config(path: str | Path) -> FrameworkConfig:
    """Load a :class:`FrameworkConfig` from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FrameworkConfig.model_validate(data)
