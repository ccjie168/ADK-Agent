"""SLICE-050: the --metrics flag on the MCP commands."""

from __future__ import annotations

from adk_agent import cli
from adk_agent.metrics import MetricsRegistry


def _patch_serve_agent(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agent", lambda path: object())
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_agent", lambda agent, **kwargs: captured.update(kwargs)
    )
    return captured


def test_serve_forwards_metrics(monkeypatch):
    captured = _patch_serve_agent(monkeypatch)

    cli.main(["serve", "--agent", "x.py", "--metrics"])

    assert isinstance(captured["metrics"], MetricsRegistry)


def test_metrics_default_off(monkeypatch):
    captured = _patch_serve_agent(monkeypatch)

    cli.main(["serve", "--agent", "x.py"])

    assert captured["metrics"] is None


def test_serve_many_forwards_metrics(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {})
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_many", lambda agents, **kwargs: captured.update(kwargs)
    )

    cli.main(["serve-many", "--agents", "x.py", "--metrics"])

    assert isinstance(captured["metrics"], MetricsRegistry)
