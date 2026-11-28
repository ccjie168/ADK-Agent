"""SLICE-319: google.adk lives only in the adapter (ADR-0046 3c)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adk_wall  # noqa: E402

SOURCE = ROOT / "src" / "adk_agent"
ADAPTER = SOURCE / "adapters" / "adk"

SANDBOX_MODULES = frozenset(
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


def _imports_adk(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("google.adk") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("google.adk"):
                return True
            if node.module == "google" and any(alias.name == "adk" for alias in node.names):
                return True
    return False


def test_no_module_imports_adk_outside_the_adapter():
    assert adk_wall.importers() == {}
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in SOURCE.rglob("*.py")
        if ADAPTER not in path.parents and _imports_adk(path)
    ]
    assert offenders == []


def test_baseline_is_empty():
    assert frozenset() == adk_wall.BASELINE
    assert SANDBOX_MODULES.isdisjoint(adk_wall.importers())


def test_adapter_exports_the_sandbox_types():
    from adk_agent.adapters.adk.agents import BaseAgent, InvocationContext
    from adk_agent.adapters.adk.events import Event
    from adk_agent.adapters.adk.tools import BaseTool, BaseToolset

    assert issubclass(BaseAgent, object)
    assert InvocationContext is not None
    assert issubclass(Event, object)
    assert BaseTool is not None
    assert BaseToolset is not None


def test_upgrade_runbook_covers_the_drill():
    text = (ROOT / "docs" / "guides" / "adk-upgrade.md").read_text(encoding="utf-8")

    for needle in ("scripts/adk_compat.py", "scripts/check.py --full", "ADR-0046", "adk_wall"):
        assert needle in text, needle
