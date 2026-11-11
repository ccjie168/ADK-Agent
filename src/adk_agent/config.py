"""Pydantic configuration schema for adk-agent.

These models describe an agent, the LLM backend it uses, and the external MCP
servers it should consume tools from. The same schema is used by the model
factory, the agent factory, and (later) the CLI's ``new``/``serve`` commands.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Incoming MCP clients use "http". Outgoing servers expose "streamable-http".
IncomingTransport = Literal["stdio", "http"]
ExposureTransport = Literal["stdio", "streamable-http"]

_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")
_SECRET_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_secret_headers(value: dict[str, str]) -> dict[str, str]:
    for header, reference in value.items():
        if not _HEADER_NAME.fullmatch(header):
            raise ValueError(f"invalid header name {header!r}")
        if not _SECRET_REF.fullmatch(reference):
            raise ValueError(f"invalid secret reference {reference!r}")
    return value


class ModelConfig(BaseModel):
    """Which LLM backend an agent runs on."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "litellm", "claude", "vertex"] = "litellm"
    # LiteLLM model id (e.g. "deepseek/deepseek-v4-pro", "openai/gpt-4o") or
    # an ADK model id for the gemini/claude providers.
    name: str = "deepseek/deepseek-v4-pro"
    api_key: str | None = None
    api_base: str | None = None
    # Extra keyword arguments forwarded to the ADK model class.
    kwargs: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(BaseModel):
    """How to reach one external MCP server (the *incoming* direction)."""

    model_config = ConfigDict(extra="forbid")

    transport: IncomingTransport = "stdio"

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

    # Header name -> secret reference, resolved per request. HTTP only.
    header_secrets: dict[str, str] = Field(default_factory=dict)

    @field_validator("header_secrets")
    @classmethod
    def _valid_secret_headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_secret_headers(value)

    @model_validator(mode="after")
    def _secret_headers_are_http_only(self) -> McpServerConfig:
        if self.transport == "stdio" and self.header_secrets:
            raise ValueError("header_secrets require http transport")
        overlap = set(self.headers or {}) & set(self.header_secrets)
        if overlap:
            raise ValueError(f"headers and header_secrets overlap: {sorted(overlap)}")
        return self


class OpenApiConfig(BaseModel):
    """How to turn one OpenAPI JSON document into ADK tools."""

    model_config = ConfigDict(extra="forbid")

    spec_path: str = Field(min_length=1)
    tool_filter: list[str] | None = None
    tool_name_prefix: str | None = None
    header_secrets: dict[str, str] = Field(default_factory=dict)

    @field_validator("header_secrets")
    @classmethod
    def _valid_secret_headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_secret_headers(value)


class AgentConfig(BaseModel):
    """Declarative description of one ADK agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    instruction: str = ""
    # Cap or disable model thinking (0 disables it). build_agent applies this
    # to the agent's GenerateContentConfig.
    thinking_budget: int | None = None
    model: ModelConfig = Field(default_factory=ModelConfig)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    openapi: list[OpenApiConfig] = Field(default_factory=list)
    sub_agents: list[AgentConfig] = Field(default_factory=list)


class FrameworkConfig(BaseModel):
    """Top-level config: named agents plus which one to expose over MCP."""

    model_config = ConfigDict(extra="forbid")

    agents: dict[str, AgentConfig]
    expose: str | None = None
    transport: ExposureTransport = "stdio"

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
