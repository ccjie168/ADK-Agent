"""SLICE-134: console and MCP commands accept the agent sandbox flags."""

from __future__ import annotations

import argparse

import pytest

from adk_agent import cli
from adk_agent.sandbox import agent as sandbox_agent


class _Backend:
    async def run(self, artifact, data, input_text):
        raise AssertionError("backend should not run during startup")


def test_install_registers_process_backend(monkeypatch):
    from adk_agent.sandbox import agent_process

    monkeypatch.setattr(agent_process, "agent_sandbox_supported", lambda: True)
    monkeypatch.setattr(agent_process, "ProcessAgentSandbox", lambda model: _Backend())
    monkeypatch.setattr("adk_agent.models.build_model", lambda: "model")

    cli._install_agent_sandbox(argparse.Namespace(agent_sandbox=True, allow_unsandboxed=False))
    try:
        assert isinstance(sandbox_agent.agent_sandbox_backend(), _Backend)
    finally:
        sandbox_agent.set_agent_sandbox_backend(None)


def test_install_refuses_without_posix(monkeypatch, capsys):
    from adk_agent.sandbox import agent_process

    monkeypatch.setattr(agent_process, "agent_sandbox_supported", lambda: False)

    with pytest.raises(SystemExit) as exc:
        cli._install_agent_sandbox(argparse.Namespace(agent_sandbox=True, allow_unsandboxed=False))

    assert exc.value.code == 1
    assert "POSIX" in capsys.readouterr().err


def test_install_allows_override_without_posix(monkeypatch, capsys):
    from adk_agent.sandbox import agent_process

    monkeypatch.setattr(agent_process, "agent_sandbox_supported", lambda: False)
    monkeypatch.setattr(agent_process, "ProcessAgentSandbox", lambda model: _Backend())
    monkeypatch.setattr("adk_agent.models.build_model", lambda: "model")

    cli._install_agent_sandbox(argparse.Namespace(agent_sandbox=True, allow_unsandboxed=True))
    try:
        assert sandbox_agent.agent_sandbox_backend() is not None
    finally:
        sandbox_agent.set_agent_sandbox_backend(None)
    assert "without process limits" in capsys.readouterr().err


def test_console_accepts_agent_sandbox(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cli, "_load_agents", lambda path: {})
    monkeypatch.setattr(
        cli, "_install_agent_sandbox", lambda args: captured.setdefault("flag", True)
    )
    monkeypatch.setattr(
        "adk_agent.console.run_console", lambda agents, **kwargs: captured.update(kwargs)
    )

    cli.main(["console", "--agents", "x.py", "--agent-sandbox"])

    assert captured["flag"] is True
    assert "agents" not in captured or captured.get("agents") == {}


def test_serve_many_accepts_agent_sandbox(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cli, "_load_agents", lambda path: {})
    monkeypatch.setattr(
        cli, "_install_agent_sandbox", lambda args: captured.setdefault("flag", True)
    )
    monkeypatch.setattr("adk_agent.mcp.server.serve_many", lambda **kwargs: captured.update(kwargs))

    cli.main(["serve-many", "--agents", "x.py", "--agent-sandbox"])

    assert captured["flag"] is True


def test_serve_accepts_agent_sandbox(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cli, "_load_agent", lambda path: None)
    monkeypatch.setattr(
        cli, "_install_agent_sandbox", lambda args: captured.setdefault("flag", True)
    )
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_agent", lambda **kwargs: captured.update(kwargs)
    )

    cli.main(["serve", "--agent", "x.py", "--agent-sandbox"])

    assert captured["flag"] is True
