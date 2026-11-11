"""SLICE-022: HTTP tool sources are checked against the egress allowlist."""

from __future__ import annotations

import json

import pytest

from adk_agent.config import AgentConfig
from adk_agent.factory import build_agent
from adk_agent.sandbox import SandboxViolation
from adk_agent.secretstore import MappingSecretProvider

_MODEL = {"provider": "gemini", "name": "gemini-2.5-pro"}


def _write_spec(tmp_path, server_url: str) -> str:
    path = tmp_path / "openapi.json"
    path.write_text(
        json.dumps(
            {
                "openapi": "3.0.3",
                "info": {"title": "Demo", "version": "1.0.0"},
                "servers": [{"url": server_url}],
                "paths": {
                    "/ping": {
                        "get": {
                            "operationId": "ping",
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_mcp_url_denied():
    config = AgentConfig(
        name="agent",
        model=_MODEL,
        sandbox={"allowed_hosts": ["api.example.com"]},
        mcp_servers=[{"transport": "http", "url": "https://evil.example.com/mcp"}],
    )
    with pytest.raises(SandboxViolation):
        build_agent(config, MappingSecretProvider({}))


def test_mcp_url_allowed():
    config = AgentConfig(
        name="agent",
        model=_MODEL,
        sandbox={"allowed_hosts": ["api.example.com"]},
        mcp_servers=[{"transport": "http", "url": "https://api.example.com/mcp"}],
    )
    agent = build_agent(config, MappingSecretProvider({}))
    assert len(agent.tools) == 1


def test_openapi_host_denied(tmp_path):
    path = _write_spec(tmp_path, "https://evil.example.com")
    config = AgentConfig(
        name="agent",
        model=_MODEL,
        sandbox={"allowed_hosts": ["api.example.com"]},
        openapi=[{"spec_path": path}],
    )
    with pytest.raises(SandboxViolation):
        build_agent(config, MappingSecretProvider({}))


def test_none_allowlist_allows(tmp_path):
    path = _write_spec(tmp_path, "https://evil.example.com")
    config = AgentConfig(
        name="agent",
        model=_MODEL,
        openapi=[{"spec_path": path}],
    )
    agent = build_agent(config, MappingSecretProvider({}))
    assert len(agent.tools) == 1


def test_empty_allowlist_denies_all(tmp_path):
    path = _write_spec(tmp_path, "https://api.example.com")
    config = AgentConfig(
        name="agent",
        model=_MODEL,
        sandbox={"allowed_hosts": []},
        openapi=[{"spec_path": path}],
    )
    with pytest.raises(SandboxViolation):
        build_agent(config, MappingSecretProvider({}))
