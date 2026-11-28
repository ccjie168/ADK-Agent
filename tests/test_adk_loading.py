"""SLICE-317: loading and trigger paths go through the adapter (ADR-0046 3a)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adk_wall  # noqa: E402

SOURCE = ROOT / "src" / "adk_agent"

LOADING_MODULES = frozenset(
    {
        "adk_agent.factory",
        "adk_agent.registry.loader",
        "adk_agent.triggers_service",
    }
)

REMAINING = frozenset(
    {
        "adk_agent.mcp.client",
        "adk_agent.models",
        "adk_agent.models.gateway_llm",
        "adk_agent.sandbox.agent_channel",
        "adk_agent.sandbox.agent_process",
        "adk_agent.sandbox.agent_worker",
        "adk_agent.sandbox.proxy",
        "adk_agent.sandbox.runner",
        "adk_agent.tools.enforcement",
        "adk_agent.tools.guard",
        "adk_agent.tools.sources",
    }
)


def test_loading_modules_leave_the_wall():
    assert LOADING_MODULES.isdisjoint(adk_wall.importers()), sorted(
        LOADING_MODULES & set(adk_wall.importers())
    )


def test_baseline_is_models_tools_and_sandbox():
    assert adk_wall.BASELINE == REMAINING


def test_loading_modules_have_no_adk_text():
    offenders = []
    for module in ("factory.py", "registry/loader.py", "triggers_service.py"):
        text = (SOURCE / module).read_text(encoding="utf-8")
        if "google.adk" in text:
            offenders.append(module)

    assert offenders == []


def test_build_agent_returns_an_adk_agent():
    from adk_agent.adapters.adk.agents import BaseAgent
    from adk_agent.config import AgentConfig
    from adk_agent.factory import build_agent

    agent = build_agent(AgentConfig(name="probe", instruction="hello"))

    assert isinstance(agent, BaseAgent)
    assert agent.name == "probe"


def test_build_runner_uses_the_adapter_runner(tmp_path):
    from adk_agent.adapters.adk.runner import Runner
    from adk_agent.config import AgentConfig
    from adk_agent.factory import build_agent, build_runner

    agent = build_agent(AgentConfig(name="probe", instruction="x"))
    runner = build_runner(agent, str(tmp_path / "sessions.db"))

    assert isinstance(runner, Runner)
    assert runner.agent is agent
