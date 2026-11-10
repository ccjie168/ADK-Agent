"""SLICE-002: container-ready HTTP server (/healthz, $PORT)."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from adk_agent.mcp.http import build_http_app, resolve_port


def _app(token: str = "secret"):
    server = MCPServer(name="deploy_probe")
    return build_http_app(server, auth_token=token, host="127.0.0.1")


def test_resolve_port(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert resolve_port(None) == 8000
    monkeypatch.setenv("PORT", "8080")
    assert resolve_port(None) == 8080
    assert resolve_port(9000) == 9000
    monkeypatch.setenv("PORT", "not-a-number")
    with pytest.raises(ValueError):
        resolve_port(None)


def test_healthz_open_mcp_protected():
    with TestClient(_app()) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        mcp = client.post("/mcp", json={})
        assert mcp.status_code == 401


def test_healthz_has_no_extra_fields():
    with TestClient(_app()) as client:
        body = client.get("/healthz").json()
    assert set(body) == {"status"}
