"""Tests for scripts/sbom.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_sbom():
    path = ROOT / "scripts" / "sbom.py"
    spec = importlib.util.spec_from_file_location("sbom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_command_uses_cyclonedx():
    sbom = _load_sbom()
    cmd = sbom.build_command("sbom.json")
    assert "cyclonedx-json" in cmd
    assert "pip_audit" in cmd
