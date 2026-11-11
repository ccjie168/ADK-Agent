"""SLICE-006: auth guards live in the app builders."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from mcp.server.mcpserver import MCPServer

from adk_agent.console import build_console_app
from adk_agent.mcp.http import build_http_app


def _server() -> MCPServer:
    return MCPServer(name="auth_builder_probe")


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def test_http_builder_requires_auth():
    with pytest.raises(ValueError):
        build_http_app(_server(), auth_token=None)


def test_http_builder_rejects_open_public_bind():
    with pytest.raises(ValueError):
        build_http_app(_server(), auth_token=None, allow_unauthenticated=True, host="0.0.0.0")


def test_console_builder_requires_auth():
    with pytest.raises(ValueError):
        build_console_app(_agents(), auth_token=None)


def test_builders_allow_unauthenticated_on_loopback():
    http_app = build_http_app(_server(), auth_token=None, allow_unauthenticated=True)
    assert http_app is not None
    console_app = build_console_app(_agents(), auth_token=None, allow_unauthenticated=True)
    with TestClient(console_app) as client:
        assert client.get("/api/agents").status_code == 200
