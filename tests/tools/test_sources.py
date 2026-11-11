"""SLICE-021: OpenAPI documents become ADK toolsets with secret headers."""

from __future__ import annotations

import asyncio
import json

import pytest

from adk_agent.config import AgentConfig, OpenApiConfig
from adk_agent.factory import build_agent
from adk_agent.secretstore import MappingSecretProvider
from adk_agent.tools.sources import (
    load_openapi_spec,
    openapi_toolset_from_config,
    toolset_tool_ids,
)


def _write_spec(tmp_path):
    path = tmp_path / "openapi.json"
    path.write_text(
        json.dumps(
            {
                "openapi": "3.0.3",
                "info": {"title": "Demo API", "version": "1.0.0"},
                "servers": [{"url": "https://api.example.com"}],
                "paths": {
                    "/users/{id}": {
                        "get": {
                            "operationId": "getUser",
                            "parameters": [
                                {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string"},
                                }
                            ],
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_openapi_toolset_from_json(tmp_path):
    path = _write_spec(tmp_path)
    toolset = openapi_toolset_from_config(
        OpenApiConfig(spec_path=str(path)), MappingSecretProvider({})
    )
    assert toolset_tool_ids(toolset) == {"get_user"}


def test_openapi_tool_ids_apply_prefix(tmp_path):
    path = _write_spec(tmp_path)
    toolset = openapi_toolset_from_config(
        OpenApiConfig(spec_path=str(path), tool_name_prefix="crm"),
        MappingSecretProvider({}),
    )
    assert toolset_tool_ids(toolset) == {"crm_get_user"}


def test_openapi_tool_filter_limits_ids(tmp_path):
    path = _write_spec(tmp_path)
    toolset = openapi_toolset_from_config(
        OpenApiConfig(spec_path=str(path), tool_filter=["get_user"]),
        MappingSecretProvider({}),
    )
    assert toolset_tool_ids(toolset) == {"get_user"}


def test_openapi_header_secrets(tmp_path):
    path = _write_spec(tmp_path)
    toolset = openapi_toolset_from_config(
        OpenApiConfig(spec_path=str(path), header_secrets={"Authorization": "DEMO_TOKEN"}),
        MappingSecretProvider({"DEMO_TOKEN": "value"}),
    )
    assert asyncio.run(toolset._header_provider(None)) == {"Authorization": "value"}


def test_openapi_rejects_non_object(tmp_path):
    path = tmp_path / "openapi.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_openapi_spec(str(path))
    with pytest.raises(ValueError):
        openapi_toolset_from_config(OpenApiConfig(spec_path=str(path)), MappingSecretProvider({}))


def test_build_agent_includes_openapi_toolset(tmp_path):
    path = _write_spec(tmp_path)
    config = AgentConfig(
        name="api_agent",
        model={"provider": "gemini", "name": "gemini-2.5-pro"},
        openapi=[{"spec_path": str(path)}],
    )
    agent = build_agent(config, MappingSecretProvider({}))
    assert len(agent.tools) == 1
    assert agent.tools[0].__class__.__name__ == "OpenAPIToolset"
