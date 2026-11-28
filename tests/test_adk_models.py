"""SLICE-318: model and tool-source construction goes through the adapter (ADR-0046 3b)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adk_wall  # noqa: E402

MIGRATED = frozenset(
    {
        "adk_agent.mcp.client",
        "adk_agent.models",
        "adk_agent.models.gateway_llm",
        "adk_agent.tools.sources",
    }
)

REMAINING = frozenset(
    {
        "adk_agent.sandbox.agent_channel",
        "adk_agent.sandbox.agent_process",
        "adk_agent.sandbox.agent_worker",
        "adk_agent.sandbox.proxy",
        "adk_agent.sandbox.runner",
        "adk_agent.tools.enforcement",
        "adk_agent.tools.guard",
    }
)


def test_model_and_tool_modules_leave_the_wall():
    assert MIGRATED.isdisjoint(adk_wall.importers()), sorted(MIGRATED & set(adk_wall.importers()))


def test_baseline_is_sandbox_and_guards():
    # Slice 3b left these 7 importers; later slices may only remove them.
    assert adk_wall.BASELINE <= REMAINING


def test_model_builders_return_adk_models():
    from adk_agent.adapters.adk.models import BaseLlm, gemini_model
    from adk_agent.models import build_model

    assert isinstance(gemini_model("gemini-2.5-pro"), BaseLlm)
    assert isinstance(build_model("gemini:gemini-2.5-pro"), BaseLlm)


def test_mcp_toolset_builds_through_the_adapter():
    from google.adk.tools.mcp_tool import McpToolset

    from adk_agent.config import McpServerConfig
    from adk_agent.mcp.client import toolset_from_config

    toolset = toolset_from_config(McpServerConfig(transport="stdio", command="echo"))

    assert isinstance(toolset, McpToolset)


def test_openapi_toolset_builds_through_the_adapter(tmp_path):
    from google.adk.tools.openapi_tool import OpenAPIToolset

    from adk_agent.adapters.adk.tools import openapi_toolset

    spec = {
        "openapi": "3.0.0",
        "info": {"title": "probe", "version": "1"},
        "paths": {
            "/ping": {"get": {"operationId": "ping", "responses": {"200": {"description": "ok"}}}}
        },
    }
    toolset = openapi_toolset(spec_dict=spec)

    assert isinstance(toolset, OpenAPIToolset)
