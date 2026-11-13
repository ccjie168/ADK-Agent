"""SLICE-059: MCP and A2A endpoints honour the ingress rate limit."""

from __future__ import annotations

import importlib.util

import pytest
from google.adk.agents import LlmAgent
from google.adk.dependencies._mcp import FastMCP
from starlette.testclient import TestClient

from adk_agent import cli
from adk_agent.a2a import build_a2a_app
from adk_agent.mcp.http import build_http_app
from adk_agent.mcp.server import serve_many
from adk_agent.metrics import MetricsRegistry
from adk_agent.ratelimit import RateLimit

AUTH = {"Authorization": "Bearer secret"}
_HAS_A2A = importlib.util.find_spec("a2a") is not None
needs_a2a = pytest.mark.skipif(not _HAS_A2A, reason="a2a-sdk is not installed")


def _agent() -> LlmAgent:
    return LlmAgent(name="probe", model="gemini-2.5-pro", description="probe", instruction="x")


def _mcp_app(limit: int, *, metrics: MetricsRegistry | None = None):
    return build_http_app(
        FastMCP(name="probe"),
        auth_token="secret",
        rate_limit=RateLimit(limit=limit, window_seconds=60),
        metrics=metrics,
    )


def test_mcp_rate_limited():
    with TestClient(_mcp_app(1)) as client:
        first = client.get("/nope", headers=AUTH)
        second = client.get("/nope", headers=AUTH)

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.json() == {"error": "rate_limited"}
    assert int(second.headers["Retry-After"]) >= 1


def test_mcp_exempt_paths():
    with TestClient(_mcp_app(1, metrics=MetricsRegistry())) as client:
        assert client.get("/nope", headers=AUTH).status_code != 429
        assert client.get("/healthz").status_code == 200
        assert client.get("/metrics", headers=AUTH).status_code == 200
        assert client.get("/metrics", headers=AUTH).status_code == 200
        assert client.get("/nope", headers=AUTH).status_code == 429


def test_mcp_metric():
    metrics = MetricsRegistry()

    with TestClient(_mcp_app(1, metrics=metrics)) as client:
        client.get("/nope", headers=AUTH)
        client.get("/nope", headers=AUTH)

    assert 'adk_http_rate_limited_total{surface="mcp"} 1' in metrics.render()


def test_mcp_auth_precedes_limit():
    with TestClient(_mcp_app(1)) as client:
        assert client.get("/nope").status_code == 401
        assert client.get("/nope").status_code == 401


@needs_a2a
def test_a2a_rate_limited():
    app = build_a2a_app(
        _agent(),
        auth_token="secret",
        rate_limit=RateLimit(limit=1, window_seconds=60),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.get("/", headers=AUTH)
        second = client.get("/", headers=AUTH)

    assert first.status_code != 429
    assert second.status_code == 429


@needs_a2a
def test_a2a_auth_precedes_limit():
    app = build_a2a_app(
        _agent(),
        auth_token="secret",
        rate_limit=RateLimit(limit=1, window_seconds=60),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/").status_code == 401
        assert client.get("/").status_code == 401


def _agent_file(tmp_path) -> str:
    path = tmp_path / "agent.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agent = LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')\n",
        encoding="utf-8",
    )
    return str(path)


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.mark.parametrize("command", range(4))
def test_cli_rejects_bad_flags(tmp_path, capsys, command):
    agent = _agent_file(tmp_path)
    commands = [
        ["serve", "--agent", agent, "--rate-limit", "0"],
        ["serve-many", "--agents", _agents_file(tmp_path), "--rate-limit", "0"],
        ["serve-a2a", "--agent", agent, "--rate-limit", "0"],
        ["serve-a2a", "--agent", agent, "--rate-limit-window", "5"],
    ]

    with pytest.raises(SystemExit) as exc:
        cli.main(commands[command])

    assert exc.value.code == 1
    assert "rate-limit" in capsys.readouterr().err


def test_library_rejects_stdio_rate_limit():
    with pytest.raises(ValueError, match="streamable-http"):
        serve_many(
            {"probe": _agent()},
            transport="stdio",
            rate_limit=RateLimit(limit=1, window_seconds=60),
        )


def test_stdio_rejects_rate_limit(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--agent", _agent_file(tmp_path), "--rate-limit", "5"])

    assert exc.value.code == 1
    assert "streamable-http" in capsys.readouterr().err
