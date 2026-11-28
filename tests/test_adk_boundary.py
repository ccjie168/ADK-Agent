"""SLICE-314: the ADK import wall and the compatibility drill (ADR-0046)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adk_wall  # noqa: E402


def test_adk_wall_has_no_unlisted_importers():
    assert adk_wall.violations() == [], adk_wall.violations()


def test_adk_wall_baseline_matches_reality():
    assert set(adk_wall.importers()) == adk_wall.BASELINE


def test_adapter_package_is_the_only_allowed_importer():
    assert adk_wall.ALLOWED_PREFIX == "adk_agent.adapters.adk"
    assert (ROOT / "src" / "adk_agent" / "adapters" / "adk" / "__init__.py").is_file()


def test_adk_compat_drill_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "adk_compat.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in ("runner", "events", "mcp", "agent-to-mcp", "a2a-executor"):
        assert f"PASS {name}" in proc.stdout, name
    assert "ALL PASS" in proc.stdout


def test_agent_runtime_port_is_exported():
    from adk_agent.core import AgentRuntime

    assert hasattr(AgentRuntime, "load")
    assert hasattr(AgentRuntime, "run")


def test_adk_wall_catches_parent_package_import(tmp_path):
    module = tmp_path / "bad.py"
    module.write_text("from google import adk\n", encoding="utf-8")

    assert adk_wall.violations(tmp_path) == ["adk_agent.bad"]
