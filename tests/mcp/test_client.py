"""SLICE-021: MCP toolsets resolve secret headers and declare tool names."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from adk_agent.config import McpServerConfig
from adk_agent.mcp.client import toolset_from_config
from adk_agent.secretstore import MappingSecretProvider
from adk_agent.tools.sources import toolset_tool_ids


def _http_config(**overrides):
    data = {"transport": "http", "url": "https://mcp.example.com/mcp"}
    data.update(overrides)
    return McpServerConfig(**data)


def test_http_toolset_resolves_header_secrets():
    config = _http_config(header_secrets={"Authorization": "DEMO_TOKEN"})
    toolset = toolset_from_config(config, MappingSecretProvider({"DEMO_TOKEN": "value"}))
    assert asyncio.run(toolset.header_provider(None)) == {"Authorization": "value"}


def test_header_secrets_require_provider():
    config = _http_config(header_secrets={"Authorization": "DEMO_TOKEN"})
    with pytest.raises(ValueError):
        toolset_from_config(config, None)


def test_stdio_header_secrets_rejected():
    with pytest.raises(ValidationError):
        McpServerConfig(
            transport="stdio",
            command="echo",
            header_secrets={"Authorization": "DEMO_TOKEN"},
        )


def test_overlapping_headers_rejected():
    with pytest.raises(ValidationError):
        _http_config(
            headers={"Authorization": "literal"},
            header_secrets={"Authorization": "DEMO_TOKEN"},
        )


def test_secret_reference_must_be_env_name():
    with pytest.raises(ValidationError):
        _http_config(header_secrets={"Authorization": "sk-live-value"})


def test_tool_filter_is_declared():
    config = _http_config(tool_filter=["read_file", "list_directory"])
    toolset = toolset_from_config(config, MappingSecretProvider({}))
    assert toolset_tool_ids(toolset) == {"read_file", "list_directory"}


def test_tool_filter_is_prefixed():
    config = _http_config(tool_filter=["read_file"], tool_name_prefix="fs")
    toolset = toolset_from_config(config, MappingSecretProvider({}))
    assert toolset_tool_ids(toolset) == {"fs_read_file"}
