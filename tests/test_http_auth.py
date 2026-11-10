"""SLICE-001: streamable-http must require bearer auth (CP-S6)."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from adk_agent.mcp.http import build_http_app, resolve_http_auth


def _app(token: str):
    server = MCPServer(name="auth_probe")
    return build_http_app(server, auth_token=token, host="127.0.0.1")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def _running(app, port: int):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_http_rejects_unauthenticated_public_bind():
    with pytest.raises(ValueError):
        resolve_http_auth("0.0.0.0", None, allow_unauthenticated=False)
    with pytest.raises(ValueError):
        resolve_http_auth("0.0.0.0", None, allow_unauthenticated=True)
    assert resolve_http_auth("127.0.0.1", None, allow_unauthenticated=True) is None
    assert resolve_http_auth("127.0.0.1", "secret", allow_unauthenticated=False) == "secret"


def test_http_requires_bearer():
    with TestClient(_app("secret")) as client:
        resp = client.post("/mcp", json={})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_http_rejects_wrong_token():
    with TestClient(_app("secret")) as client:
        resp = client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_http_accepts_correct_token():
    with TestClient(_app("secret")) as client:
        resp = client.post("/mcp", json={}, headers={"Authorization": "Bearer secret"})
    assert resp.status_code != 401


def test_http_mcp_client_roundtrip():
    port = _free_port()
    with _running(_app("secret"), port):

        async def run():
            # trust_env=False: a system HTTP proxy (e.g. Privoxy) must not
            # intercept the loopback request.
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer secret"}, trust_env=False
            ) as http:
                url = f"http://127.0.0.1:{port}/mcp"
                async with (
                    streamable_http_client(url, http_client=http) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    init = await session.initialize()
                    tools = await session.list_tools()
                    return init, tools

        init, tools = asyncio.run(run())

    assert init.server_info is not None
    assert isinstance(tools.tools, list)
